package k8scontroller

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	corev1 "k8s.io/api/core/v1"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labcontroller"
	"cla-platform/services/environment-controller/internal/labplan"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

const (
	DefaultOrphanScanInterval = 5 * time.Minute
	DefaultOrphanGracePeriod  = 10 * time.Minute
)

type OrphanScanner struct {
	Reconciler  *Reconciler
	Interval    time.Duration
	GracePeriod time.Duration
}

func (s OrphanScanner) Start(ctx context.Context) error {
	if s.Reconciler == nil {
		return fmt.Errorf("reconciler is required")
	}
	interval := s.Interval
	if interval <= 0 {
		interval = DefaultOrphanScanInterval
	}
	if _, err := s.RunOnce(ctx); err != nil {
		slog.Warn("orphan namespace cleanup failed", "error", err)
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if _, err := s.RunOnce(ctx); err != nil {
				slog.Warn("orphan namespace cleanup failed", "error", err)
			}
		}
	}
}

func (s OrphanScanner) RunOnce(ctx context.Context) ([]labreconcile.Action, error) {
	if s.Reconciler == nil {
		return nil, fmt.Errorf("reconciler is required")
	}
	startedAt := time.Now()
	gracePeriod := s.GracePeriod
	if gracePeriod <= 0 {
		gracePeriod = DefaultOrphanGracePeriod
	}
	actions, err := s.Reconciler.CleanupOrphans(ctx, gracePeriod)
	if s.Reconciler.Metrics != nil {
		s.Reconciler.Metrics.ObserveOrphanCleanup(startedAt, actions)
	}
	return actions, err
}

func (r *Reconciler) CleanupOrphans(ctx context.Context, gracePeriod time.Duration) ([]labreconcile.Action, error) {
	input, err := r.OrphanScanInput(ctx, gracePeriod)
	if err != nil {
		return nil, err
	}
	return labcontroller.Reconciler{
		Store: &Store{Client: r.Client},
	}.CleanupOrphans(ctx, input)
}

func (r *Reconciler) OrphanScanInput(ctx context.Context, gracePeriod time.Duration) (labreconcile.OrphanScanInput, error) {
	var sessions cla.LabSessionList
	if err := r.List(ctx, &sessions); err != nil {
		return labreconcile.OrphanScanInput{}, err
	}
	active := map[string]bool{}
	for _, session := range sessions.Items {
		if session.Spec.AttemptID == "" || session.Spec.Epoch <= 0 {
			continue
		}
		active[labplan.NamespaceName(session.Spec)] = true
	}

	var namespaces corev1.NamespaceList
	if err := r.List(ctx, &namespaces); err != nil {
		return labreconcile.OrphanScanInput{}, err
	}
	refs := make([]labreconcile.NamespaceRef, 0, len(namespaces.Items))
	for _, namespace := range namespaces.Items {
		refs = append(refs, labreconcile.NamespaceRef{
			Name:      namespace.Name,
			Labels:    namespace.Labels,
			CreatedAt: namespace.CreationTimestamp.Time,
		})
	}

	now := time.Now().UTC()
	if r.Now != nil {
		now = r.Now().UTC()
	}
	return labreconcile.OrphanScanInput{
		Now:              now,
		ActiveNamespaces: active,
		Namespaces:       refs,
		GracePeriod:      gracePeriod,
	}, nil
}
