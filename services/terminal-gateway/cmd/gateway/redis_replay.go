package main

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"strconv"
	"strings"
	"time"

	"cla-platform/services/terminal-gateway/internal/protocol"
)

const (
	defaultRedisReplayOperationTimeout = 500 * time.Millisecond
	defaultRedisReplayStateTTL         = 24 * time.Hour
	defaultRedisReplayKeyPrefix        = "cla:terminal-gateway:replay"
)

type redisReplayStore struct {
	client      redisDoer
	local       *replayStore
	window      time.Duration
	maxBytes    int
	stateTTL    time.Duration
	keyPrefix   string
	currentTime func() time.Time
}

type redisDoer interface {
	do(args ...[]byte) (redisReply, error)
}

type redisReply struct {
	kind    redisReplyKind
	payload []byte
	integer int64
}

type redisReplyKind int

const (
	redisReplyNil redisReplyKind = iota
	redisReplySimple
	redisReplyBulk
	redisReplyInteger
)

type redisReplaySnapshot struct {
	Frames []redisReplayFrame `json:"frames"`
}

type redisReplayFrame struct {
	Seq        uint64 `json:"seq"`
	AtUnixNano int64  `json:"at_unix_nano"`
	Frame      []byte `json:"frame"`
}

type redisClient struct {
	addr     string
	password string
	database string
	timeout  time.Duration
}

func replayFromEnv() replayBufferStore {
	addr := os.Getenv("CLA_REDIS_ADDR")
	if addr == "" {
		return newReplayStore(defaultReplayWindow, defaultReplayMaxBytes)
	}
	return newRedisReplayStore(redisReplayConfig{
		addr:      addr,
		password:  os.Getenv("CLA_REDIS_PASSWORD"),
		database:  os.Getenv("CLA_REDIS_DB"),
		keyPrefix: env("CLA_REDIS_KEY_PREFIX", defaultRedisReplayKeyPrefix),
		window:    defaultReplayWindow,
		maxBytes:  defaultReplayMaxBytes,
		stateTTL:  redisReplayStateTTL(defaultReplayWindow),
		timeout:   defaultRedisReplayOperationTimeout,
	})
}

type redisReplayConfig struct {
	addr      string
	password  string
	database  string
	keyPrefix string
	window    time.Duration
	maxBytes  int
	stateTTL  time.Duration
	timeout   time.Duration
}

func newRedisReplayStore(cfg redisReplayConfig) *redisReplayStore {
	timeout := cfg.timeout
	if timeout <= 0 {
		timeout = defaultRedisReplayOperationTimeout
	}
	stateTTL := cfg.stateTTL
	if stateTTL <= 0 {
		stateTTL = redisReplayStateTTL(cfg.window)
	}
	keyPrefix := cfg.keyPrefix
	if keyPrefix == "" {
		keyPrefix = defaultRedisReplayKeyPrefix
	}
	window := cfg.window
	if window <= 0 {
		window = defaultReplayWindow
	}
	maxBytes := cfg.maxBytes
	if maxBytes <= 0 {
		maxBytes = defaultReplayMaxBytes
	}
	return &redisReplayStore{
		client: &redisClient{
			addr:     cfg.addr,
			password: cfg.password,
			database: cfg.database,
			timeout:  timeout,
		},
		local:       newReplayStore(window, maxBytes),
		window:      window,
		maxBytes:    maxBytes,
		stateTTL:    stateTTL,
		keyPrefix:   keyPrefix,
		currentTime: time.Now,
	}
}

func newRedisReplayStoreForTest(client redisDoer, window time.Duration, maxBytes int) *redisReplayStore {
	return &redisReplayStore{
		client:      client,
		local:       newReplayStore(window, maxBytes),
		window:      window,
		maxBytes:    maxBytes,
		stateTTL:    redisReplayStateTTL(window),
		keyPrefix:   defaultRedisReplayKeyPrefix,
		currentTime: time.Now,
	}
}

func redisReplayStateTTL(window time.Duration) time.Duration {
	if window <= 0 {
		return defaultRedisReplayStateTTL
	}
	if window*10 > defaultRedisReplayStateTTL {
		return window * 10
	}
	return defaultRedisReplayStateTTL
}

func (s *redisReplayStore) appendOutput(key string, payload []byte) []byte {
	seq, err := s.nextRedisSequence(key)
	if err != nil {
		slog.Warn("redis replay sequence unavailable; using local replay buffer", "error", err)
		return s.local.appendOutput(key, payload)
	}
	frame := make([]byte, 9+len(payload))
	frame[0] = protocol.ServerStdout
	binary.BigEndian.PutUint64(frame[1:9], seq)
	copy(frame[9:], payload)
	stored := replayFrame{
		seq:   seq,
		at:    s.currentTime(),
		frame: append([]byte(nil), frame...),
	}
	if err := s.appendRedisFrame(key, stored); err != nil {
		slog.Warn("redis replay append failed; mirrored local replay buffer only", "error", err)
	}
	s.local.appendPreframedOutput(key, stored)
	return frame
}

func (s *redisReplayStore) replayAfter(key string, lastSeq uint64) ([]replayFrame, bool) {
	frames, gap, err := s.replayAfterRedis(key, lastSeq)
	if err != nil {
		slog.Warn("redis replay lookup failed; using local replay buffer", "error", err)
		return s.local.replayAfter(key, lastSeq)
	}
	return frames, gap
}

func (s *redisReplayStore) nextSequence(key string) uint64 {
	next, err := s.readRedisNextSequence(key)
	if err != nil || next == 0 {
		return s.local.nextSequence(key)
	}
	return next
}

func (s *redisReplayStore) nextRedisSequence(key string) (uint64, error) {
	reply, err := s.client.do([]byte("INCR"), []byte(s.sequenceKey(key)))
	if err != nil {
		return 0, err
	}
	if reply.kind != redisReplyInteger || reply.integer <= 0 {
		return 0, fmt.Errorf("unexpected INCR reply kind=%d integer=%d", reply.kind, reply.integer)
	}
	if _, err := s.client.do(
		[]byte("EXPIRE"),
		[]byte(s.sequenceKey(key)),
		[]byte(strconv.FormatInt(int64(s.stateTTL.Seconds()), 10)),
	); err != nil {
		return 0, err
	}
	return uint64(reply.integer - 1), nil
}

func (s *redisReplayStore) readRedisNextSequence(key string) (uint64, error) {
	reply, err := s.client.do([]byte("GET"), []byte(s.sequenceKey(key)))
	if err != nil {
		return 0, err
	}
	if reply.kind == redisReplyNil {
		return 0, nil
	}
	if reply.kind != redisReplyBulk {
		return 0, fmt.Errorf("unexpected GET reply for sequence key: %d", reply.kind)
	}
	next, err := strconv.ParseUint(string(reply.payload), 10, 64)
	if err != nil {
		return 0, err
	}
	return next, nil
}

func (s *redisReplayStore) appendRedisFrame(key string, frame replayFrame) error {
	snapshot, err := s.readSnapshot(key)
	if err != nil {
		return err
	}
	snapshot.Frames = append(snapshot.Frames, redisReplayFrame{
		Seq:        frame.seq,
		AtUnixNano: frame.at.UnixNano(),
		Frame:      append([]byte(nil), frame.frame...),
	})
	s.trimSnapshot(&snapshot)
	return s.writeSnapshot(key, snapshot)
}

func (s *redisReplayStore) replayAfterRedis(key string, lastSeq uint64) ([]replayFrame, bool, error) {
	nextSeq, err := s.readRedisNextSequence(key)
	if err != nil {
		return nil, false, err
	}
	if nextSeq == 0 || lastSeq+1 >= nextSeq {
		return nil, false, nil
	}
	snapshot, err := s.readSnapshot(key)
	if err != nil {
		return nil, false, err
	}
	s.trimSnapshot(&snapshot)
	if len(snapshot.Frames) == 0 {
		return nil, true, nil
	}
	if snapshot.Frames[0].Seq > lastSeq+1 {
		return nil, true, nil
	}
	frames := make([]replayFrame, 0, len(snapshot.Frames))
	for _, frame := range snapshot.Frames {
		if frame.Seq > lastSeq {
			frames = append(frames, replayFrame{
				seq:   frame.Seq,
				at:    time.Unix(0, frame.AtUnixNano),
				frame: append([]byte(nil), frame.Frame...),
			})
		}
	}
	if len(frames) == 0 {
		return nil, false, nil
	}
	return frames, false, nil
}

func (s *redisReplayStore) readSnapshot(key string) (redisReplaySnapshot, error) {
	reply, err := s.client.do([]byte("GET"), []byte(s.bufferKey(key)))
	if err != nil {
		return redisReplaySnapshot{}, err
	}
	if reply.kind == redisReplyNil {
		return redisReplaySnapshot{}, nil
	}
	if reply.kind != redisReplyBulk {
		return redisReplaySnapshot{}, fmt.Errorf("unexpected GET reply for replay key: %d", reply.kind)
	}
	var snapshot redisReplaySnapshot
	if err := json.Unmarshal(reply.payload, &snapshot); err != nil {
		return redisReplaySnapshot{}, err
	}
	return snapshot, nil
}

func (s *redisReplayStore) writeSnapshot(key string, snapshot redisReplaySnapshot) error {
	body, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	_, err = s.client.do(
		[]byte("SETEX"),
		[]byte(s.bufferKey(key)),
		[]byte(strconv.FormatInt(int64(s.stateTTL.Seconds()), 10)),
		body,
	)
	return err
}

func (s *redisReplayStore) trimSnapshot(snapshot *redisReplaySnapshot) {
	cutoff := s.currentTime().Add(-s.window).UnixNano()
	for len(snapshot.Frames) > 0 && snapshot.Frames[0].AtUnixNano < cutoff {
		snapshot.Frames = snapshot.Frames[1:]
	}
	bytesUsed := 0
	for _, frame := range snapshot.Frames {
		bytesUsed += len(frame.Frame)
	}
	for len(snapshot.Frames) > 0 && bytesUsed > s.maxBytes {
		bytesUsed -= len(snapshot.Frames[0].Frame)
		snapshot.Frames = snapshot.Frames[1:]
	}
}

func (s *redisReplayStore) bufferKey(key string) string {
	return s.keyPrefix + ":buffer:" + key
}

func (s *redisReplayStore) sequenceKey(key string) string {
	return s.keyPrefix + ":seq:" + key
}

func (c *redisClient) do(args ...[]byte) (redisReply, error) {
	if c.addr == "" {
		return redisReply{}, errors.New("redis address is empty")
	}
	timeout := c.timeout
	if timeout <= 0 {
		timeout = defaultRedisReplayOperationTimeout
	}
	conn, err := net.DialTimeout("tcp", c.addr, timeout)
	if err != nil {
		return redisReply{}, err
	}
	defer conn.Close()
	if err := conn.SetDeadline(time.Now().Add(timeout)); err != nil {
		return redisReply{}, err
	}
	reader := bufio.NewReader(conn)
	if c.password != "" {
		if err := redisWriteCommand(conn, []byte("AUTH"), []byte(c.password)); err != nil {
			return redisReply{}, err
		}
		if _, err := redisReadReply(reader); err != nil {
			return redisReply{}, err
		}
	}
	if c.database != "" {
		if err := redisWriteCommand(conn, []byte("SELECT"), []byte(c.database)); err != nil {
			return redisReply{}, err
		}
		if _, err := redisReadReply(reader); err != nil {
			return redisReply{}, err
		}
	}
	if err := redisWriteCommand(conn, args...); err != nil {
		return redisReply{}, err
	}
	return redisReadReply(reader)
}

func redisWriteCommand(w io.Writer, args ...[]byte) error {
	var buf bytes.Buffer
	buf.WriteByte('*')
	buf.WriteString(strconv.Itoa(len(args)))
	buf.WriteString("\r\n")
	for _, arg := range args {
		buf.WriteByte('$')
		buf.WriteString(strconv.Itoa(len(arg)))
		buf.WriteString("\r\n")
		buf.Write(arg)
		buf.WriteString("\r\n")
	}
	_, err := w.Write(buf.Bytes())
	return err
}

func redisReadReply(reader *bufio.Reader) (redisReply, error) {
	prefix, err := reader.ReadByte()
	if err != nil {
		return redisReply{}, err
	}
	switch prefix {
	case '+':
		line, err := redisReadLine(reader)
		if err != nil {
			return redisReply{}, err
		}
		return redisReply{kind: redisReplySimple, payload: line}, nil
	case '-':
		line, err := redisReadLine(reader)
		if err != nil {
			return redisReply{}, err
		}
		return redisReply{}, fmt.Errorf("redis error: %s", line)
	case ':':
		line, err := redisReadLine(reader)
		if err != nil {
			return redisReply{}, err
		}
		value, err := strconv.ParseInt(string(line), 10, 64)
		if err != nil {
			return redisReply{}, err
		}
		return redisReply{kind: redisReplyInteger, integer: value}, nil
	case '$':
		line, err := redisReadLine(reader)
		if err != nil {
			return redisReply{}, err
		}
		size, err := strconv.Atoi(string(line))
		if err != nil {
			return redisReply{}, err
		}
		if size == -1 {
			return redisReply{kind: redisReplyNil}, nil
		}
		payload := make([]byte, size+2)
		if _, err := io.ReadFull(reader, payload); err != nil {
			return redisReply{}, err
		}
		if !bytes.HasSuffix(payload, []byte("\r\n")) {
			return redisReply{}, errors.New("malformed redis bulk reply")
		}
		return redisReply{kind: redisReplyBulk, payload: payload[:size]}, nil
	default:
		return redisReply{}, fmt.Errorf("unsupported redis reply prefix %q", prefix)
	}
}

func redisReadLine(reader *bufio.Reader) ([]byte, error) {
	line, err := reader.ReadBytes('\n')
	if err != nil {
		return nil, err
	}
	if len(line) < 2 || !strings.HasSuffix(string(line), "\r\n") {
		return nil, errors.New("malformed redis line")
	}
	return line[:len(line)-2], nil
}
