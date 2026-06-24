package main

import (
	"encoding/binary"
	"strconv"
	"sync"
	"time"

	"cla-platform/services/terminal-gateway/internal/protocol"
	"cla-platform/services/terminal-gateway/internal/tickets"
)

const (
	defaultReplayWindow   = 60 * time.Second
	defaultReplayMaxBytes = 1 << 20
)

type replayStore struct {
	mu       sync.Mutex
	window   time.Duration
	maxBytes int
	sessions map[string]*replayBuffer
}

type replayBufferStore interface {
	appendOutput(key string, payload []byte) []byte
	replayAfter(key string, lastSeq uint64) ([]replayFrame, bool)
	nextSequence(key string) uint64
}

type replayBuffer struct {
	frames  []replayFrame
	bytes   int
	nextSeq uint64
}

type replayFrame struct {
	seq   uint64
	at    time.Time
	frame []byte
}

func newReplayStore(window time.Duration, maxBytes int) *replayStore {
	return &replayStore{
		window:   window,
		maxBytes: maxBytes,
		sessions: make(map[string]*replayBuffer),
	}
}

func replayKey(route tickets.Route) string {
	return route.TenantID + "/" + route.AttemptID + "/" + route.SessionID + "/" + strconv.Itoa(route.SessionEpoch) + "/" + route.SessionRoute.RouteRef
}

func (s *replayStore) appendOutput(key string, payload []byte) []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	buffer := s.sessions[key]
	if buffer == nil {
		buffer = &replayBuffer{}
		s.sessions[key] = buffer
	}
	seq := buffer.nextSeq
	buffer.nextSeq++
	frame := make([]byte, 9+len(payload))
	frame[0] = protocol.ServerStdout
	binary.BigEndian.PutUint64(frame[1:9], seq)
	copy(frame[9:], payload)
	s.appendFrameLocked(buffer, replayFrame{
		seq:   seq,
		at:    time.Now(),
		frame: append([]byte(nil), frame...),
	})
	return frame
}

func (s *replayStore) appendPreframedOutput(key string, frame replayFrame) {
	s.mu.Lock()
	defer s.mu.Unlock()
	buffer := s.sessions[key]
	if buffer == nil {
		buffer = &replayBuffer{}
		s.sessions[key] = buffer
	}
	s.appendFrameLocked(buffer, frame)
}

func (s *replayStore) replayAfter(key string, lastSeq uint64) ([]replayFrame, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	buffer := s.sessions[key]
	if buffer == nil || buffer.nextSeq == 0 || lastSeq+1 >= buffer.nextSeq {
		return nil, false
	}
	s.trimLocked(buffer)
	if len(buffer.frames) == 0 {
		return nil, true
	}
	if buffer.frames[0].seq > lastSeq+1 {
		return nil, true
	}
	frames := make([]replayFrame, 0, len(buffer.frames))
	for _, frame := range buffer.frames {
		if frame.seq > lastSeq {
			frames = append(frames, replayFrame{
				seq:   frame.seq,
				at:    frame.at,
				frame: append([]byte(nil), frame.frame...),
			})
		}
	}
	return frames, false
}

func (s *replayStore) nextSequence(key string) uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	buffer := s.sessions[key]
	if buffer == nil {
		return 0
	}
	return buffer.nextSeq
}

func (s *replayStore) appendFrameLocked(buffer *replayBuffer, frame replayFrame) {
	copied := replayFrame{
		seq:   frame.seq,
		at:    frame.at,
		frame: append([]byte(nil), frame.frame...),
	}
	buffer.frames = append(buffer.frames, copied)
	buffer.bytes += len(copied.frame)
	if buffer.nextSeq <= copied.seq {
		buffer.nextSeq = copied.seq + 1
	}
	s.trimLocked(buffer)
}

func (s *replayStore) trimLocked(buffer *replayBuffer) {
	cutoff := time.Now().Add(-s.window)
	for len(buffer.frames) > 0 && buffer.frames[0].at.Before(cutoff) {
		buffer.bytes -= len(buffer.frames[0].frame)
		buffer.frames = buffer.frames[1:]
	}
	for len(buffer.frames) > 0 && buffer.bytes > s.maxBytes {
		buffer.bytes -= len(buffer.frames[0].frame)
		buffer.frames = buffer.frames[1:]
	}
}
