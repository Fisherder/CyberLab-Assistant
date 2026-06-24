package labreconcile

import (
	"testing"
	"time"

	cla "cla-platform/services/environment-controller/api/v1"
)

func TestReconcileAddsFinalizerAndAppliesResources(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: defaultMetadata(),
		Now:      fixedNow(),
	})
	if decision.Status.Phase != string(cla.SessionPending) {
		t.Fatalf("phase = %s", decision.Status.Phase)
	}
	if !containsFinalizer(decision.Finalizers) {
		t.Fatalf("finalizer not planned: %#v", decision.Finalizers)
	}
	assertAction(t, decision, ActionAddFinalizer)
	assertAction(t, decision, ActionApplyResources)
	assertAction(t, decision, ActionEmitStatusEvent)
	if decision.Status.NamespaceName != "lab-a-123-e2" {
		t.Fatalf("namespace = %q", decision.Status.NamespaceName)
	}
	if decision.Status.Components["workspace"] != cla.ComponentPending {
		t.Fatalf("workspace should be pending: %#v", decision.Status.Components)
	}
}

func TestReconcileWaitsForHealthBeforeRouteRegistration(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			TargetReady:     false,
			OracleReady:     true,
		},
		Now: fixedNow(),
	})
	if decision.Status.Phase != string(cla.SessionProvisioning) {
		t.Fatalf("phase = %s", decision.Status.Phase)
	}
	assertAction(t, decision, ActionPollHealth)
	assertNoAction(t, decision, ActionRegisterRoute)
}

func TestReconcileRegistersRouteOnlyAfterRequiredComponentsReady(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			TargetReady:     true,
			OracleReady:     true,
		},
		Now: fixedNow(),
	})
	if decision.Status.RouteReady {
		t.Fatalf("route should not be marked ready before registration")
	}
	assertAction(t, decision, ActionRegisterRoute)
}

func TestReconcileReadyKeepsRouteAndRequeuesAtTTL(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			TargetReady:     true,
			OracleReady:     true,
			RouteRegistered: true,
		},
		Now: fixedNow(),
	})
	if decision.Status.Phase != string(cla.SessionReady) || !decision.Status.RouteReady {
		t.Fatalf("not ready: %#v", decision.Status)
	}
	if decision.RequeueAfter != 20*time.Minute {
		t.Fatalf("requeue = %s", decision.RequeueAfter)
	}
	assertNoAction(t, decision, ActionApplyResources)
	assertNoAction(t, decision, ActionRegisterRoute)
}

func TestReconcileExpiresSessionAndDeletesNamespace(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			RouteRegistered: true,
		},
		Now: fixedNow().Add(time.Hour),
	})
	if decision.Status.Phase != string(cla.SessionExpired) {
		t.Fatalf("phase = %s", decision.Status.Phase)
	}
	assertAction(t, decision, ActionExpireSession)
	assertAction(t, decision, ActionRevokeTickets)
	assertAction(t, decision, ActionUnregisterRoute)
	assertAction(t, decision, ActionDeleteNamespace)
	if decision.Status.RouteReady {
		t.Fatalf("expired session should not remain route ready")
	}
}

func TestReconcileFinalizerRemainsUntilCleanupVerified(t *testing.T) {
	deletedAt := fixedNow()
	decision := Reconcile(Input{
		Spec:      defaultSpec(),
		Metadata:  Metadata{Name: "lab-a-123-e2", CreatedAt: fixedNow().Add(-40 * time.Minute), DeletedAt: &deletedAt, Finalizers: []string{FinalizerName}},
		Resources: ResourceState{RouteRegistered: true, CleanupComplete: false},
		Now:       fixedNow(),
	})
	if decision.Status.Phase != string(cla.SessionTerminating) {
		t.Fatalf("phase = %s", decision.Status.Phase)
	}
	assertAction(t, decision, ActionRevokeTickets)
	assertAction(t, decision, ActionUnregisterRoute)
	assertAction(t, decision, ActionDeleteNamespace)
	assertAction(t, decision, ActionVerifyNoResiduals)
	assertNoAction(t, decision, ActionRemoveFinalizer)
	if !containsFinalizer(decision.Finalizers) {
		t.Fatalf("finalizer removed before cleanup verification")
	}
}

func TestReconcileRemovesFinalizerAfterCleanupVerified(t *testing.T) {
	deletedAt := fixedNow()
	decision := Reconcile(Input{
		Spec:      defaultSpec(),
		Metadata:  Metadata{Name: "lab-a-123-e2", CreatedAt: fixedNow().Add(-40 * time.Minute), DeletedAt: &deletedAt, Finalizers: []string{FinalizerName}},
		Resources: ResourceState{CleanupComplete: true},
		Now:       fixedNow(),
	})
	assertAction(t, decision, ActionRemoveFinalizer)
	if containsFinalizer(decision.Finalizers) {
		t.Fatalf("finalizer still present after cleanup verification: %#v", decision.Finalizers)
	}
}

func TestReconcileFailsInvalidWorkspaceTypeWithoutResourceActions(t *testing.T) {
	spec := defaultSpec()
	spec.WorkspaceType = cla.WorkspaceRemoteDesktop
	decision := Reconcile(Input{
		Spec:     spec,
		Metadata: defaultMetadata(),
		Now:      fixedNow(),
	})
	if decision.Status.Phase != string(cla.SessionFailed) || decision.Status.Reason != "InvalidSpec" {
		t.Fatalf("unexpected status: %#v", decision.Status)
	}
	assertAction(t, decision, ActionRecordFailure)
	assertNoAction(t, decision, ActionApplyResources)
	assertNoAction(t, decision, ActionAddFinalizer)
}

func TestReconcileMarksFailedComponentsAndDoesNotRegisterRoute(t *testing.T) {
	decision := Reconcile(Input{
		Spec:     defaultSpec(),
		Metadata: metadataWithFinalizer(),
		Resources: ResourceState{
			NamespaceExists: true,
			ResourcesSynced: true,
			WorkspaceReady:  true,
			Failed: map[string]string{
				"target": "readiness probe failed",
			},
		},
		Now: fixedNow(),
	})
	if decision.Status.Components["target"] != cla.ComponentFailed {
		t.Fatalf("target should be failed: %#v", decision.Status.Components)
	}
	assertAction(t, decision, ActionRecordFailure)
	assertAction(t, decision, ActionRevokeTickets)
	assertAction(t, decision, ActionUnregisterRoute)
	assertAction(t, decision, ActionEmitStatusEvent)
	assertNoAction(t, decision, ActionRegisterRoute)
}

func TestPlanOrphanCleanupTargetsOnlyUnownedLabNamespaces(t *testing.T) {
	actions := PlanOrphanCleanup(OrphanScanInput{
		Now:              fixedNow(),
		GracePeriod:      10 * time.Minute,
		ActiveNamespaces: map[string]bool{"lab-active-e1": true},
		Namespaces: []NamespaceRef{
			{Name: "lab-active-e1", Labels: labLabels(), CreatedAt: fixedNow().Add(-time.Hour)},
			{Name: "lab-orphan-e2", Labels: labLabels(), CreatedAt: fixedNow().Add(-time.Hour)},
			{Name: "lab-new-e3", Labels: labLabels(), CreatedAt: fixedNow().Add(-time.Minute)},
			{Name: "default", Labels: map[string]string{}, CreatedAt: fixedNow().Add(-time.Hour)},
		},
	})
	if len(actions) != 2 {
		t.Fatalf("actions = %#v", actions)
	}
	if actions[0].Type != ActionCleanupOrphan || actions[0].Target != "lab-orphan-e2" {
		t.Fatalf("unexpected cleanup action: %#v", actions[0])
	}
	if actions[1].Type != ActionVerifyOrphanDelete || actions[1].Target != "lab-orphan-e2" {
		t.Fatalf("unexpected verify action: %#v", actions[1])
	}
}

func fixedNow() time.Time {
	return time.Date(2026, 6, 24, 10, 0, 0, 0, time.UTC)
}

func defaultMetadata() Metadata {
	return Metadata{
		Name:      "lab-a-123-e2",
		CreatedAt: fixedNow().Add(-70 * time.Minute),
	}
}

func metadataWithFinalizer() Metadata {
	metadata := defaultMetadata()
	metadata.Finalizers = []string{FinalizerName}
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

func containsFinalizer(finalizers []string) bool {
	for _, finalizer := range finalizers {
		if finalizer == FinalizerName {
			return true
		}
	}
	return false
}

func assertAction(t *testing.T, decision Decision, actionType ActionType) {
	t.Helper()
	for _, action := range decision.Actions {
		if action.Type == actionType {
			return
		}
	}
	t.Fatalf("missing action %s in %#v", actionType, decision.Actions)
}

func assertNoAction(t *testing.T, decision Decision, actionType ActionType) {
	t.Helper()
	for _, action := range decision.Actions {
		if action.Type == actionType {
			t.Fatalf("unexpected action %s in %#v", actionType, decision.Actions)
		}
	}
}
