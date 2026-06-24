package main

import (
	"bufio"
	"bytes"
	"errors"
	"strconv"
	"strings"
	"sync"
	"testing"
)

func TestRedisReplayStoreReturnsFramesAfterLastSequence(t *testing.T) {
	client := newMemoryRedisClient()
	store := newRedisReplayStoreForTest(client, defaultReplayWindow, defaultReplayMaxBytes)
	key := fakeReplayKey("127.0.0.1:0")
	store.appendOutput(key, []byte("first"))
	store.appendOutput(key, []byte("second"))

	frames, gap := store.replayAfter(key, 0)

	if gap {
		t.Fatal("gap = true")
	}
	if len(frames) != 1 {
		t.Fatalf("frames = %d, want 1", len(frames))
	}
	if frames[0].seq != 1 {
		t.Fatalf("seq = %d, want 1", frames[0].seq)
	}
	if got := string(frames[0].frame[9:]); got != "second" {
		t.Fatalf("payload = %q, want second", got)
	}
	if next := store.nextSequence(key); next != 2 {
		t.Fatalf("next sequence = %d, want 2", next)
	}
}

func TestRedisReplayStoreDetectsGapWhenBufferedFramesAreTrimmed(t *testing.T) {
	client := newMemoryRedisClient()
	store := newRedisReplayStoreForTest(client, defaultReplayWindow, 12)
	key := fakeReplayKey("127.0.0.1:0")
	store.appendOutput(key, []byte("first"))
	store.appendOutput(key, []byte("second"))

	frames, gap := store.replayAfter(key, 0)

	if !gap {
		t.Fatalf("gap = false, frames = %d", len(frames))
	}
}

func TestRedisReplayStoreFallsBackToLocalBufferWhenRedisFails(t *testing.T) {
	store := newRedisReplayStoreForTest(failingRedisClient{}, defaultReplayWindow, defaultReplayMaxBytes)
	key := fakeReplayKey("127.0.0.1:0")
	store.appendOutput(key, []byte("first"))
	store.appendOutput(key, []byte("second"))

	frames, gap := store.replayAfter(key, 0)

	if gap {
		t.Fatal("gap = true")
	}
	if len(frames) != 1 {
		t.Fatalf("frames = %d, want 1", len(frames))
	}
	if got := string(frames[0].frame[9:]); got != "second" {
		t.Fatalf("payload = %q, want second", got)
	}
}

func TestRedisWriteCommandUsesRESPArrayEncoding(t *testing.T) {
	var buf bytes.Buffer

	if err := redisWriteCommand(&buf, []byte("SETEX"), []byte("key"), []byte("60"), []byte("value")); err != nil {
		t.Fatal(err)
	}

	want := "*4\r\n$5\r\nSETEX\r\n$3\r\nkey\r\n$2\r\n60\r\n$5\r\nvalue\r\n"
	if got := buf.String(); got != want {
		t.Fatalf("RESP = %q, want %q", got, want)
	}
}

func TestRedisReadReplyParsesBulkNilAndInteger(t *testing.T) {
	bulk, err := redisReadReply(bufio.NewReader(strings.NewReader("$5\r\nhello\r\n")))
	if err != nil {
		t.Fatal(err)
	}
	if bulk.kind != redisReplyBulk || string(bulk.payload) != "hello" {
		t.Fatalf("bulk reply = %#v", bulk)
	}
	nilReply, err := redisReadReply(bufio.NewReader(strings.NewReader("$-1\r\n")))
	if err != nil {
		t.Fatal(err)
	}
	if nilReply.kind != redisReplyNil {
		t.Fatalf("nil reply kind = %d", nilReply.kind)
	}
	integer, err := redisReadReply(bufio.NewReader(strings.NewReader(":42\r\n")))
	if err != nil {
		t.Fatal(err)
	}
	if integer.kind != redisReplyInteger || integer.integer != 42 {
		t.Fatalf("integer reply = %#v", integer)
	}
}

type memoryRedisClient struct {
	mu      sync.Mutex
	values  map[string][]byte
	numbers map[string]int64
}

func newMemoryRedisClient() *memoryRedisClient {
	return &memoryRedisClient{
		values:  make(map[string][]byte),
		numbers: make(map[string]int64),
	}
}

func (c *memoryRedisClient) do(args ...[]byte) (redisReply, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(args) == 0 {
		return redisReply{}, errors.New("empty command")
	}
	command := strings.ToUpper(string(args[0]))
	switch command {
	case "INCR":
		if len(args) != 2 {
			return redisReply{}, errors.New("INCR expects key")
		}
		key := string(args[1])
		c.numbers[key]++
		return redisReply{kind: redisReplyInteger, integer: c.numbers[key]}, nil
	case "EXPIRE":
		return redisReply{kind: redisReplyInteger, integer: 1}, nil
	case "GET":
		if len(args) != 2 {
			return redisReply{}, errors.New("GET expects key")
		}
		key := string(args[1])
		if value, ok := c.values[key]; ok {
			return redisReply{kind: redisReplyBulk, payload: append([]byte(nil), value...)}, nil
		}
		if value, ok := c.numbers[key]; ok {
			return redisReply{kind: redisReplyBulk, payload: []byte(strconv.FormatInt(value, 10))}, nil
		}
		return redisReply{kind: redisReplyNil}, nil
	case "SETEX":
		if len(args) != 4 {
			return redisReply{}, errors.New("SETEX expects key ttl value")
		}
		c.values[string(args[1])] = append([]byte(nil), args[3]...)
		return redisReply{kind: redisReplySimple, payload: []byte("OK")}, nil
	default:
		return redisReply{}, errors.New("unexpected command: " + command)
	}
}

type failingRedisClient struct{}

func (failingRedisClient) do(args ...[]byte) (redisReply, error) {
	return redisReply{}, errors.New("redis unavailable")
}
