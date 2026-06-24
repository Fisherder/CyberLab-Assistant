package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"
)

const defaultRecordingQueueSize = 1024

type recordingSink interface {
	Enqueue(transcriptSegment)
}

type transcriptSegment struct {
	AttemptID  string
	Epoch      int
	Direction  string
	SeqFrom    uint64
	SeqTo      uint64
	Payload    []byte
	EnqueuedAt time.Time
}

type transcriptRecorder struct {
	apiURL       string
	serviceToken string
	httpClient   *http.Client
	metrics      *Metrics
	queue        chan transcriptSegment
	stop         chan struct{}
	wg           sync.WaitGroup
}

func newTranscriptRecorder(apiURL, serviceToken string, metrics *Metrics, queueSize int) *transcriptRecorder {
	if queueSize <= 0 {
		queueSize = defaultRecordingQueueSize
	}
	recorder := &transcriptRecorder{
		apiURL:       strings.TrimRight(apiURL, "/"),
		serviceToken: serviceToken,
		httpClient:   &http.Client{Timeout: 5 * time.Second},
		metrics:      metrics,
		queue:        make(chan transcriptSegment, queueSize),
		stop:         make(chan struct{}),
	}
	recorder.wg.Add(1)
	go recorder.run()
	return recorder
}

func (r *transcriptRecorder) Enqueue(segment transcriptSegment) {
	if r == nil || segment.AttemptID == "" || len(segment.Payload) == 0 {
		return
	}
	copied := segment
	copied.Payload = append([]byte(nil), segment.Payload...)
	copied.EnqueuedAt = time.Now()
	select {
	case r.queue <- copied:
	default:
		if r.metrics != nil {
			r.metrics.ObserveRecordingDrop()
		}
	}
}

func (r *transcriptRecorder) Stop() {
	if r == nil {
		return
	}
	close(r.stop)
	r.wg.Wait()
}

func (r *transcriptRecorder) run() {
	defer r.wg.Done()
	for {
		select {
		case <-r.stop:
			return
		case segment := <-r.queue:
			if err := r.upload(context.Background(), segment); err != nil && r.metrics != nil {
				r.metrics.ObserveRecordingFailure()
			}
		}
	}
}

func (r *transcriptRecorder) upload(ctx context.Context, segment transcriptSegment) error {
	if r == nil {
		return nil
	}
	if r.apiURL == "" {
		return fmt.Errorf("api url is required")
	}
	body, err := json.Marshal(map[string]any{
		"sessionEpoch":  segment.Epoch,
		"direction":     segment.Direction,
		"seqFrom":       segment.SeqFrom,
		"seqTo":         segment.SeqTo,
		"segmentBase64": base64.StdEncoding.EncodeToString(segment.Payload),
	})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		r.apiURL+"/internal/attempts/"+segment.AttemptID+"/transcript-segments/upload",
		bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CLA-Service-Token", r.serviceToken)
	resp, err := r.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("transcript upload rejected: status %d", resp.StatusCode)
	}
	if r.metrics != nil && !segment.EnqueuedAt.IsZero() {
		r.metrics.SetRecordingLag(time.Since(segment.EnqueuedAt).Seconds())
	}
	return nil
}

type noopRecorder struct{}

func (noopRecorder) Enqueue(transcriptSegment) {}
