package main

import (
	"sync"

	"github.com/prometheus/client_golang/prometheus"
)

type Metrics struct {
	activeConnections prometheus.Gauge
	terminalBytes     *prometheus.CounterVec
	unackedBytes      prometheus.Gauge
	reconnects        prometheus.Counter
	ticketRejects     prometheus.Counter
	replayGaps        prometheus.Counter
	recordingLag      prometheus.Gauge
	recordingDrops    prometheus.Counter
	recordingFailures prometheus.Counter
}

var (
	defaultMetricsOnce sync.Once
	defaultMetrics     *Metrics
)

func NewMetrics(registerer prometheus.Registerer) *Metrics {
	metrics := &Metrics{
		activeConnections: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "active_connections",
			Help:      "Current active terminal WebSocket connections.",
		}),
		terminalBytes: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "terminal_bytes_total",
			Help:      "Terminal bytes relayed by the gateway.",
		}, []string{"direction"}),
		unackedBytes: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "unacked_window_bytes",
			Help:      "Current aggregate bytes waiting for client ACK across terminal connections.",
		}),
		reconnects: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "reconnects_total",
			Help:      "Total terminal reconnect attempts carrying last_server_sequence.",
		}),
		ticketRejects: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "ticket_rejects_total",
			Help:      "Total terminal ticket validation failures observed by the gateway.",
		}),
		replayGaps: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "replay_gaps_total",
			Help:      "Total reconnect replay requests that could not be satisfied from the replay buffer.",
		}),
		recordingLag: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "recording_lag_seconds",
			Help:      "Age in seconds of the most recently uploaded terminal transcript segment.",
		}),
		recordingDrops: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "recording_drops_total",
			Help:      "Total transcript recording segments dropped because the async queue was full.",
		}),
		recordingFailures: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "terminal_gateway",
			Name:      "recording_failures_total",
			Help:      "Total transcript recording upload failures.",
		}),
	}
	if registerer != nil {
		registerer.MustRegister(
			metrics.activeConnections,
			metrics.terminalBytes,
			metrics.unackedBytes,
			metrics.reconnects,
			metrics.ticketRejects,
			metrics.replayGaps,
			metrics.recordingLag,
			metrics.recordingDrops,
			metrics.recordingFailures,
		)
	}
	return metrics
}

func DefaultMetrics() *Metrics {
	defaultMetricsOnce.Do(func() {
		defaultMetrics = NewMetrics(prometheus.DefaultRegisterer)
	})
	return defaultMetrics
}

func (m *Metrics) ObserveConnectionOpened() {
	if m == nil {
		return
	}
	m.activeConnections.Inc()
}

func (m *Metrics) ObserveConnectionClosed() {
	if m == nil {
		return
	}
	m.activeConnections.Dec()
}

func (m *Metrics) AddTerminalBytes(direction string, count int) {
	if m == nil || count <= 0 {
		return
	}
	m.terminalBytes.WithLabelValues(direction).Add(float64(count))
}

func (m *Metrics) AddUnackedBytes(delta int) {
	if m == nil || delta == 0 {
		return
	}
	m.unackedBytes.Add(float64(delta))
}

func (m *Metrics) ObserveReconnect() {
	if m == nil {
		return
	}
	m.reconnects.Inc()
}

func (m *Metrics) ObserveTicketReject() {
	if m == nil {
		return
	}
	m.ticketRejects.Inc()
}

func (m *Metrics) ObserveReplayGap() {
	if m == nil {
		return
	}
	m.replayGaps.Inc()
}

func (m *Metrics) SetRecordingLag(seconds float64) {
	if m == nil || seconds < 0 {
		return
	}
	m.recordingLag.Set(seconds)
}

func (m *Metrics) ObserveRecordingDrop() {
	if m == nil {
		return
	}
	m.recordingDrops.Inc()
}

func (m *Metrics) ObserveRecordingFailure() {
	if m == nil {
		return
	}
	m.recordingFailures.Inc()
}
