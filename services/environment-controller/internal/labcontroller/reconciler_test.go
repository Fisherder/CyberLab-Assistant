package labcontroller

import (
	"context"
	"strconv"
	"testing"
	"time"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labplan"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

func TestReconcilerAppliesResourcesAndPatchesStatus(t *testing.T) {
	store := &fakeStore{}
	decision, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec:     defaultSpec(),
		Metadata: defaultMetadata(),
		Now:      fixedNow(),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	if decision.Status.Phase != string(cla.SessionPending) {
		t.Fatalf("phase = %s", decision.Status.Phase)
	}
	assertCall(t, store, "PatchFinalizers:lab-a-123-e2")
	assertCall(t, store, "ApplyResources:lab-a-123-e2:11")
	assertCall(t, store, "PatchStatus:lab-a-123-e2:Pending")
	if store.appliedSecret != "session-secret" {
		t.Fatalf("secret was not passed to resource planner")
	}
}

func TestReconcilerRegistersRouteAfterHealthReady(t *testing.T) {
	store := &fakeStore{}
	_, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: labreconcile.ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			TargetReady:     true,
			OracleReady:     true,
		},
		Now: fixedNow(),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	if store.route.RouteRef != "route_123" || store.route.Namespace != "lab-a-123-e2" {
		t.Fatalf("route registration = %#v", store.route)
	}
	if store.route.ServiceName != WorkspaceServiceName || store.route.Port != SessiondPort {
		t.Fatalf("route should point at sessiond service: %#v", store.route)
	}
	assertCall(t, store, "RegisterRoute:route_123:lab-a-123-e2:workspace-sessiond:7777")
}

func TestReconcilerFinalizesOnlyAfterCleanupActions(t *testing.T) {
	deletedAt := fixedNow()
	store := &fakeStore{}
	_, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec: defaultSpec(),
		Metadata: labreconcile.Metadata{
			Name:       "lab-a-123-e2",
			CreatedAt:  fixedNow().Add(-40 * time.Minute),
			DeletedAt:  &deletedAt,
			Finalizers: []string{labreconcile.FinalizerName},
		},
		Resources: labreconcile.ResourceState{CleanupComplete: true},
		Now:       fixedNow(),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	assertCall(t, store, "RevokeTickets:route_123")
	assertCall(t, store, "UnregisterRoute:route_123")
	assertCall(t, store, "DeleteNamespace:lab-a-123-e2")
	assertCall(t, store, "VerifyNoResidualResources:lab-a-123-e2")
	assertCall(t, store, "PatchFinalizers:lab-a-123-e2")
	if len(store.finalizers) != 0 {
		t.Fatalf("finalizer not removed: %#v", store.finalizers)
	}
}

func TestReconcilerExpiresSessionSeparatelyFromFailure(t *testing.T) {
	store := &fakeStore{}
	_, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: labreconcile.ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			RouteRegistered: true,
		},
		Now: fixedNow().Add(time.Hour),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	assertCall(t, store, "ExpireSession:lab-a-123-e2")
	assertCall(t, store, "RevokeTickets:route_123")
	assertNoCall(t, store, "RecordFailure:lab-a-123-e2")
}

func TestReconcilerComponentFailureRevokesTicketsAndRoute(t *testing.T) {
	store := &fakeStore{}
	_, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: labreconcile.ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			Failed: map[string]string{
				"target": "ProgressDeadlineExceeded: target pod never became ready",
			},
		},
		Now: fixedNow(),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	assertCall(t, store, "RecordFailure:lab-a-123-e2")
	assertCall(t, store, "RevokeTickets:route_123")
	assertCall(t, store, "UnregisterRoute:route_123")
	assertCall(t, store, "EmitStatusEvent:lab-a-123-e2")
	assertNoCall(t, store, "RegisterRoute:route_123:lab-a-123-e2:workspace-sessiond:7777")
}

func TestReconcilerInvalidSpecRecordsFailureWithoutApplyingResources(t *testing.T) {
	spec := defaultSpec()
	spec.WorkspaceType = cla.WorkspaceRemoteDesktop
	store := &fakeStore{}
	_, err := testReconciler(store).Reconcile(context.Background(), labreconcile.Input{
		Spec:     spec,
		Metadata: defaultMetadata(),
		Now:      fixedNow(),
	})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	assertCall(t, store, "RecordFailure:lab-a-123-e2")
	assertNoCall(t, store, "ApplyResources:lab-a-123-e2:11")
}

func TestReconcilerCleanupOrphansDeletesAndVerifiesOnlyPlannedNamespaces(t *testing.T) {
	store := &fakeStore{}
	actions, err := testReconciler(store).CleanupOrphans(context.Background(), labreconcile.OrphanScanInput{
		Now:              fixedNow(),
		GracePeriod:      10 * time.Minute,
		ActiveNamespaces: map[string]bool{"lab-active-e1": true},
		Namespaces: []labreconcile.NamespaceRef{
			{Name: "lab-active-e1", Labels: labLabels(), CreatedAt: fixedNow().Add(-time.Hour)},
			{Name: "lab-orphan-e2", Labels: labLabels(), CreatedAt: fixedNow().Add(-time.Hour)},
		},
	})
	if err != nil {
		t.Fatalf("orphan cleanup failed: %v", err)
	}
	if len(actions) != 2 {
		t.Fatalf("actions = %#v", actions)
	}
	assertCall(t, store, "DeleteNamespace:lab-orphan-e2")
	assertCall(t, store, "VerifyNoResidualResources:lab-orphan-e2")
	assertNoCall(t, store, "DeleteNamespace:lab-active-e1")
}

func testReconciler(store *fakeStore) Reconciler {
	return Reconciler{
		Store:        store,
		SecretSource: StaticSecretProvider{Secrets: labplan.SecretSet{TargetSessionKey: "session-secret"}},
	}
}

func fixedNow() time.Time {
	return time.Date(2026, 6, 24, 10, 0, 0, 0, time.UTC)
}

func defaultMetadata() labreconcile.Metadata {
	return labreconcile.Metadata{
		Name:      "lab-a-123-e2",
		CreatedAt: fixedNow().Add(-70 * time.Minute),
	}
}

func metadataWithFinalizer() labreconcile.Metadata {
	metadata := defaultMetadata()
	metadata.Finalizers = []string{labreconcile.FinalizerName}
	return metadata
}

func defaultSpec() cla.LabSessionSpec {
	return cla.LabSessionSpec{
		TenantID:         "tenant_dev",
		AttemptID:        "a_123",
		Epoch:            2,
		WorkspaceType:    cla.WorkspaceTerminal,
		RuntimeClassName: "gvisor",
		TTLSeconds:       5400,
		RouteRef:         "route_123",
	}
}

func labLabels() map[string]string {
	return map[string]string{
		"cla.edu/tenant-id":  "tenant_dev",
		"cla.edu/attempt-id": "a_123",
		"cla.edu/epoch":      "2",
	}
}

type fakeStore struct {
	calls         []string
	finalizers    []string
	route         RouteRegistration
	appliedSecret string
}

func (s *fakeStore) PatchFinalizers(_ context.Context, name string, finalizers []string) error {
	s.finalizers = append([]string{}, finalizers...)
	s.calls = append(s.calls, "PatchFinalizers:"+name)
	return nil
}

func (s *fakeStore) PatchStatus(_ context.Context, name string, status cla.LabSessionStatus) error {
	s.calls = append(s.calls, "PatchStatus:"+name+":"+status.Phase)
	return nil
}

func (s *fakeStore) ApplyResources(_ context.Context, namespace string, objects []labplan.Object) error {
	s.calls = append(s.calls, "ApplyResources:"+namespace+":"+strconv.Itoa(len(objects)))
	for _, object := range objects {
		if object.Kind == "Secret" {
			s.appliedSecret = object.StringData["TARGET_SESSION_KEY"]
		}
	}
	return nil
}

func (s *fakeStore) PollHealth(_ context.Context, namespace string) error {
	s.calls = append(s.calls, "PollHealth:"+namespace)
	return nil
}

func (s *fakeStore) RegisterRoute(_ context.Context, route RouteRegistration) error {
	s.route = route
	s.calls = append(s.calls, "RegisterRoute:"+route.RouteRef+":"+route.Namespace+":"+route.ServiceName+":7777")
	return nil
}

func (s *fakeStore) UnregisterRoute(_ context.Context, routeRef string) error {
	s.calls = append(s.calls, "UnregisterRoute:"+routeRef)
	return nil
}

func (s *fakeStore) RevokeTickets(_ context.Context, routeRef string) error {
	s.calls = append(s.calls, "RevokeTickets:"+routeRef)
	return nil
}

func (s *fakeStore) DeleteNamespace(_ context.Context, namespace string) error {
	s.calls = append(s.calls, "DeleteNamespace:"+namespace)
	return nil
}

func (s *fakeStore) VerifyNoResidualResources(_ context.Context, namespace string) error {
	s.calls = append(s.calls, "VerifyNoResidualResources:"+namespace)
	return nil
}

func (s *fakeStore) ExpireSession(_ context.Context, name string, _ string) error {
	s.calls = append(s.calls, "ExpireSession:"+name)
	return nil
}

func (s *fakeStore) EmitStatusEvent(_ context.Context, name string, _ cla.LabSessionStatus, _ string) error {
	s.calls = append(s.calls, "EmitStatusEvent:"+name)
	return nil
}

func (s *fakeStore) RecordFailure(_ context.Context, name string, _ string) error {
	s.calls = append(s.calls, "RecordFailure:"+name)
	return nil
}

func assertCall(t *testing.T, store *fakeStore, expected string) {
	t.Helper()
	for _, call := range store.calls {
		if call == expected {
			return
		}
	}
	t.Fatalf("missing call %q in %#v", expected, store.calls)
}

func assertNoCall(t *testing.T, store *fakeStore, unexpected string) {
	t.Helper()
	for _, call := range store.calls {
		if call == unexpected {
			t.Fatalf("unexpected call %q in %#v", unexpected, store.calls)
		}
	}
}
