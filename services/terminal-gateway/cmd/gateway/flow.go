package main

import (
	"context"
	"sync"
	"time"
)

const defaultUnackedWindowBytes = 1 << 20

type flowControl struct {
	mu     sync.Mutex
	limit  int
	bytes  int
	frames map[uint64]int
}

func newFlowControl(limit int) *flowControl {
	return &flowControl{limit: limit, frames: make(map[uint64]int)}
}

func (f *flowControl) wait(ctx context.Context) bool {
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		f.mu.Lock()
		ready := f.bytes <= f.limit
		f.mu.Unlock()
		if ready {
			return true
		}
		select {
		case <-ctx.Done():
			return false
		case <-ticker.C:
		}
	}
}

func (f *flowControl) record(seq uint64, bytes int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.frames[seq] = bytes
	f.bytes += bytes
}

func (f *flowControl) ack(serverSequence uint64) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	released := 0
	for seq, bytes := range f.frames {
		if seq <= serverSequence {
			f.bytes -= bytes
			released += bytes
			delete(f.frames, seq)
		}
	}
	if f.bytes < 0 {
		f.bytes = 0
	}
	return released
}

func (f *flowControl) reset() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	pending := f.bytes
	f.bytes = 0
	f.frames = make(map[uint64]int)
	return pending
}

func (f *flowControl) pendingBytes() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.bytes
}
