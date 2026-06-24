package k8scontroller

import (
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	ctrlmetrics "sigs.k8s.io/controller-runtime/pkg/metrics"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

type Metrics struct {
	sessionProvisionDuration prometheus.Histogram
	reconcileErrors          prometheus.Counter
	orphanNamespaces         prometheus.Gauge
	orphanCleanupDuration    prometheus.Histogram
}

var (
	defaultMetricsOnce sync.Once
	defaultMetrics     *Metrics
)

func NewMetrics(registerer prometheus.Registerer) *Metrics {
	metrics := &Metrics{
		sessionProvisionDuration: prometheus.NewHistogram(prometheus.HistogramOpts{
			Namespace: "cla",
			Subsystem: "environment_controller",
			Name:      "session_provision_duration_seconds",
			Help:      "Seconds from LabSession creation to first Ready status.",
			Buckets:   prometheus.ExponentialBuckets(1, 2, 12),
		}),
		reconcileErrors: prometheus.NewCounter(prometheus.CounterOpts{
			Namespace: "cla",
			Subsystem: "environment_controller",
			Name:      "reconcile_errors_total",
			Help:      "Total LabSession reconcile errors.",
		}),
		orphanNamespaces: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "cla",
			Subsystem: "environment_controller",
			Name:      "orphan_namespaces",
			Help:      "Lab namespaces selected for orphan cleanup in the last scan.",
		}),
		orphanCleanupDuration: prometheus.NewHistogram(prometheus.HistogramOpts{
			Namespace: "cla",
			Subsystem: "environment_controller",
			Name:      "orphan_cleanup_duration_seconds",
			Help:      "Seconds spent scanning and cleaning orphan LabSession namespaces.",
			Buckets:   prometheus.ExponentialBuckets(0.01, 2, 12),
		}),
	}
	if registerer != nil {
		registerer.MustRegister(
			metrics.sessionProvisionDuration,
			metrics.reconcileErrors,
			metrics.orphanNamespaces,
			metrics.orphanCleanupDuration,
		)
	}
	return metrics
}

func DefaultMetrics() *Metrics {
	defaultMetricsOnce.Do(func() {
		defaultMetrics = NewMetrics(ctrlmetrics.Registry)
	})
	return defaultMetrics
}

func (m *Metrics) ObserveReconcileError() {
	if m == nil {
		return
	}
	m.reconcileErrors.Inc()
}

func (m *Metrics) ObserveReconcileSuccess(session *cla.LabSession, decision labreconcile.Decision, now time.Time) {
	if m == nil || session == nil {
		return
	}
	if session.Status.Phase == string(cla.SessionReady) || decision.Status.Phase != string(cla.SessionReady) {
		return
	}
	createdAt := session.CreationTimestamp.Time
	if createdAt.IsZero() || now.Before(createdAt) {
		return
	}
	m.sessionProvisionDuration.Observe(now.Sub(createdAt).Seconds())
}

func (m *Metrics) ObserveOrphanCleanup(startedAt time.Time, actions []labreconcile.Action) {
	if m == nil {
		return
	}
	m.orphanNamespaces.Set(float64(countOrphanCleanupActions(actions)))
	m.orphanCleanupDuration.Observe(time.Since(startedAt).Seconds())
}

func countOrphanCleanupActions(actions []labreconcile.Action) int {
	count := 0
	for _, action := range actions {
		if action.Type == labreconcile.ActionCleanupOrphan {
			count++
		}
	}
	return count
}
