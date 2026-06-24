package k8scontroller

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labcontroller"
	"cla-platform/services/environment-controller/internal/labplan"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

func TestK8sReconcilerAppliesResourcesFinalizerAndStatus(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())

	result, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	if result.RequeueAfter != 2*time.Second {
		t.Fatalf("requeue = %s", result.RequeueAfter)
	}

	var session cla.LabSession
	if err := c.Get(ctx, controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	if !hasFinalizer(session.Finalizers, labreconcile.FinalizerName) {
		t.Fatalf("finalizer not patched: %#v", session.Finalizers)
	}
	if session.Status.Phase != string(cla.SessionPending) {
		t.Fatalf("phase = %#v", session.Status)
	}
	if session.Status.ObservedGeneration != session.Generation {
		t.Fatalf("observedGeneration = %d, want %d", session.Status.ObservedGeneration, session.Generation)
	}

	var ns corev1.Namespace
	if err := c.Get(ctx, types.NamespacedName{Name: "lab-a-123-e2"}, &ns); err != nil {
		t.Fatalf("namespace not created: %v", err)
	}
	if ns.Labels["pod-security.kubernetes.io/enforce"] != "restricted" {
		t.Fatalf("namespace pod security labels = %#v", ns.Labels)
	}
	secret := getUnstructured(t, c, "v1", "Secret", types.NamespacedName{Name: "target-session", Namespace: "lab-a-123-e2"})
	stringData := secret.Object["stringData"].(map[string]any)
	if stringData["TARGET_SESSION_KEY"] != "session-secret" {
		t.Fatalf("secret not applied through controller: %#v", stringData)
	}
}

func TestK8sReconcilerDoesNotBlockWhenStatusEventFails(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())
	reconciler.Events = failingEventSink{}

	result, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()})
	if err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}
	if result.RequeueAfter != 2*time.Second {
		t.Fatalf("requeue = %s", result.RequeueAfter)
	}
	var session cla.LabSession
	if err := c.Get(ctx, controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	if session.Status.Phase != string(cla.SessionPending) {
		t.Fatalf("status was not patched after event failure: %#v", session.Status)
	}
	if session.Annotations[lastEventErrorAnnotation] == "" {
		t.Fatalf("event error annotation missing: %#v", session.Annotations)
	}
}

func TestK8sReconcilerRecordsKubernetesStatusEvent(t *testing.T) {
	ctx := context.Background()
	recorder := record.NewFakeRecorder(10)
	reconciler, _ := newTestReconciler(t, defaultLabSession())
	reconciler.Recorder = recorder

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}

	select {
	case event := <-recorder.Events:
		if !strings.Contains(event, "Normal LabSessionPending") {
			t.Fatalf("unexpected event = %q", event)
		}
		if !strings.Contains(event, "phase="+string(cla.SessionPending)) || !strings.Contains(event, "reconcileReason=pending") {
			t.Fatalf("event missing status context = %q", event)
		}
		forbidden := []string{"route_123", "endpoint", "sessiond", "target-session", "session-secret"}
		for _, value := range forbidden {
			if strings.Contains(event, value) {
				t.Fatalf("kubernetes event leaked %q in %q", value, event)
			}
		}
	case <-time.After(time.Second):
		t.Fatalf("expected Kubernetes status event")
	}
}

func TestK8sReconcilerRegistersRouteAndMarksReadyAfterDeploymentsReady(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first reconcile failed: %v", err)
	}
	setDeploymentReady(t, c, "lab-a-123-e2", "workspace")
	setDeploymentReady(t, c, "lab-a-123-e2", "target")
	state := (&Store{Client: c}).ResourceState(ctx, mustGetSession(t, c))
	if !state.ResourcesSynced || !state.WorkspaceReady || !state.TargetReady || !state.OracleReady {
		t.Fatalf("pre-route resource state not ready: %#v", state)
	}

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("route reconcile failed: %v", err)
	}
	var routed cla.LabSession
	if err := c.Get(ctx, controlKey(), &routed); err != nil {
		t.Fatal(err)
	}
	if routed.Annotations[routeRegisteredAnnotation] != routed.Spec.RouteRef {
		t.Fatalf("route annotation not registered: %#v", routed.Annotations)
	}
	if routed.Status.Phase != string(cla.SessionProvisioning) || routed.Status.RouteReady {
		t.Fatalf("route registration pass should remain provisioning until next observe: %#v", routed.Status)
	}

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("ready reconcile failed: %v", err)
	}
	var ready cla.LabSession
	if err := c.Get(ctx, controlKey(), &ready); err != nil {
		t.Fatal(err)
	}
	if ready.Status.Phase != string(cla.SessionReady) || !ready.Status.RouteReady {
		t.Fatalf("session not ready after observed route: %#v", ready.Status)
	}
}

func TestK8sReconcilerRegistersControlPlaneRouteBeforeRouteReady(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())
	registry := &recordingRouteRegistry{}
	reconciler.Routes = registry
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first reconcile failed: %v", err)
	}
	setDeploymentReady(t, c, "lab-a-123-e2", "workspace")
	setDeploymentReady(t, c, "lab-a-123-e2", "target")

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("route reconcile failed: %v", err)
	}
	if registry.registeredAttemptID != "a_123" || registry.registeredEpoch != 2 {
		t.Fatalf("registry target = %s/%d", registry.registeredAttemptID, registry.registeredEpoch)
	}
	if registry.registered.RouteRef != "route_123" || registry.registered.Namespace != "lab-a-123-e2" {
		t.Fatalf("registered route = %#v", registry.registered)
	}
	var routed cla.LabSession
	if err := c.Get(ctx, controlKey(), &routed); err != nil {
		t.Fatal(err)
	}
	if routed.Annotations[routeRegisteredAnnotation] != routed.Spec.RouteRef {
		t.Fatalf("route annotation not registered after registry call: %#v", routed.Annotations)
	}
}

func TestK8sReconcilerRouteRegistryFailureBlocksRouteReady(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())
	reconciler.Routes = failingRouteRegistry{}
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first reconcile failed: %v", err)
	}
	setDeploymentReady(t, c, "lab-a-123-e2", "workspace")
	setDeploymentReady(t, c, "lab-a-123-e2", "target")

	_, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()})
	if err == nil {
		t.Fatalf("expected route registry failure")
	}
	var session cla.LabSession
	if err := c.Get(ctx, controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	if session.Annotations[routeRegisteredAnnotation] != "" {
		t.Fatalf("route should not be marked registered: %#v", session.Annotations)
	}
	if session.Annotations[lastRouteErrorAnnotation] == "" {
		t.Fatalf("route error annotation missing: %#v", session.Annotations)
	}
}

func TestK8sReconcilerMarksDeploymentFailureAndRevokesRoute(t *testing.T) {
	ctx := context.Background()
	reconciler, c := newTestReconciler(t, defaultLabSession())
	registry := &recordingRouteRegistry{}
	reconciler.Routes = registry
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first reconcile failed: %v", err)
	}
	setDeploymentReady(t, c, "lab-a-123-e2", "workspace")
	setDeploymentFailed(t, c, "lab-a-123-e2", "target", "ProgressDeadlineExceeded", "target pod stayed pending after node drain")
	state := (&Store{Client: c}).ResourceState(ctx, mustGetSession(t, c))
	if state.Failed["target"] == "" {
		t.Fatalf("target failure not observed: %#v", state)
	}

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("failure reconcile failed: %v", err)
	}
	if registry.revokedRouteRef != "route_123" || registry.unregisteredRouteRef != "route_123" {
		t.Fatalf("route cleanup not requested: revoked=%q unregistered=%q", registry.revokedRouteRef, registry.unregisteredRouteRef)
	}
	var failed cla.LabSession
	if err := c.Get(ctx, controlKey(), &failed); err != nil {
		t.Fatal(err)
	}
	if failed.Status.Phase != string(cla.SessionFailed) || failed.Status.Reason != "ComponentFailed" {
		t.Fatalf("session not failed after deployment failure: %#v", failed.Status)
	}
	if failed.Status.Components["target"] != cla.ComponentFailed {
		t.Fatalf("target component should be failed: %#v", failed.Status.Components)
	}
	if failed.Annotations["cla.edu/failure-reason"] == "" {
		t.Fatalf("failure annotation missing: %#v", failed.Annotations)
	}
}

func TestK8sReconcilerRecordsControllerMetrics(t *testing.T) {
	ctx := context.Background()
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	reconciler, c := newTestReconciler(t, defaultLabSession())
	reconciler.Metrics = metrics

	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first reconcile failed: %v", err)
	}
	setDeploymentReady(t, c, "lab-a-123-e2", "workspace")
	setDeploymentReady(t, c, "lab-a-123-e2", "target")
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("route reconcile failed: %v", err)
	}
	if _, err := reconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("ready reconcile failed: %v", err)
	}

	if count := metricHistogramCount(t, registry, "cla_environment_controller_session_provision_duration_seconds"); count != 1 {
		t.Fatalf("provision duration samples = %d", count)
	}
	if sum := metricHistogramSum(t, registry, "cla_environment_controller_session_provision_duration_seconds"); sum != 3600 {
		t.Fatalf("provision duration sum = %f", sum)
	}

	failingReconciler, failingClient := newTestReconciler(t, defaultLabSession())
	failingReconciler.Metrics = metrics
	failingReconciler.Routes = failingRouteRegistry{}
	if _, err := failingReconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err != nil {
		t.Fatalf("first failing reconcile failed: %v", err)
	}
	setDeploymentReady(t, failingClient, "lab-a-123-e2", "workspace")
	setDeploymentReady(t, failingClient, "lab-a-123-e2", "target")
	if _, err := failingReconciler.Reconcile(ctx, ctrl.Request{NamespacedName: controlKey()}); err == nil {
		t.Fatalf("expected route registry error")
	}
	if value := metricValue(t, registry, "cla_environment_controller_reconcile_errors_total"); value != 1 {
		t.Fatalf("reconcile errors = %f", value)
	}
}

func TestK8sReconcilerRevokesTicketsThroughControlPlane(t *testing.T) {
	ctx := context.Background()
	_, c := newTestReconciler(t, defaultLabSession())
	registry := &recordingRouteRegistry{}
	store := &Store{
		Client:           c,
		ControlNamespace: "cla-control",
		LabSessionName:   "lab-a-123-e2",
		Spec:             defaultLabSession().Spec,
		Routes:           registry,
	}

	if err := store.RevokeTickets(ctx, "route_123"); err != nil {
		t.Fatalf("revoke tickets: %v", err)
	}
	if registry.revokedAttemptID != "a_123" || registry.revokedEpoch != 2 || registry.revokedRouteRef != "route_123" {
		t.Fatalf("revocation target = %s/%d/%s", registry.revokedAttemptID, registry.revokedEpoch, registry.revokedRouteRef)
	}
	var session cla.LabSession
	if err := c.Get(ctx, controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	if session.Annotations[lastRouteErrorAnnotation] != "" {
		t.Fatalf("route error annotation should be clear: %#v", session.Annotations)
	}
}

func TestK8sReconcilerTicketRevocationFailureBlocksCleanup(t *testing.T) {
	ctx := context.Background()
	_, c := newTestReconciler(t, defaultLabSession())
	store := &Store{
		Client:           c,
		ControlNamespace: "cla-control",
		LabSessionName:   "lab-a-123-e2",
		Spec:             defaultLabSession().Spec,
		Routes:           failingRouteRegistry{},
	}

	if err := store.RevokeTickets(ctx, "route_123"); err == nil {
		t.Fatalf("expected ticket revocation failure")
	}
	var session cla.LabSession
	if err := c.Get(ctx, controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	if session.Annotations[lastRouteErrorAnnotation] == "" {
		t.Fatalf("route error annotation missing: %#v", session.Annotations)
	}
}

func TestK8sReconcilerCleanupOrphansDeletesOnlyUnownedLabNamespaces(t *testing.T) {
	ctx := context.Background()
	active := labNamespace("lab-a-123-e2", map[string]string{
		"cla.edu/tenant-id":  "tenant_dev",
		"cla.edu/attempt-id": "a_123",
		"cla.edu/epoch":      "2",
	}, time.Date(2026, 6, 24, 9, 0, 0, 0, time.UTC))
	orphan := labNamespace("lab-orphan-e1", map[string]string{
		"cla.edu/tenant-id":  "tenant_dev",
		"cla.edu/attempt-id": "a_orphan",
		"cla.edu/epoch":      "1",
	}, time.Date(2026, 6, 24, 9, 0, 0, 0, time.UTC))
	fresh := labNamespace("lab-fresh-e1", map[string]string{
		"cla.edu/tenant-id":  "tenant_dev",
		"cla.edu/attempt-id": "a_fresh",
		"cla.edu/epoch":      "1",
	}, time.Date(2026, 6, 24, 9, 59, 0, 0, time.UTC))
	unrelated := labNamespace("default", map[string]string{}, time.Date(2026, 6, 24, 8, 0, 0, 0, time.UTC))
	reconciler, c := newTestReconciler(t, defaultLabSession(), active, orphan, fresh, unrelated)

	actions, err := (OrphanScanner{Reconciler: reconciler, GracePeriod: 10 * time.Minute}).RunOnce(ctx)
	if err != nil {
		t.Fatalf("cleanup orphans: %v", err)
	}
	if len(actions) != 2 {
		t.Fatalf("actions = %#v", actions)
	}
	if actions[0].Target != "lab-orphan-e1" || actions[1].Target != "lab-orphan-e1" {
		t.Fatalf("unexpected orphan actions: %#v", actions)
	}
	assertNamespaceExists(t, c, "lab-a-123-e2")
	assertNamespaceExists(t, c, "lab-fresh-e1")
	assertNamespaceExists(t, c, "default")
	assertNamespaceMissing(t, c, "lab-orphan-e1")
}

func TestOrphanScannerRecordsMetrics(t *testing.T) {
	ctx := context.Background()
	registry := prometheus.NewRegistry()
	metrics := NewMetrics(registry)
	orphan := labNamespace("lab-orphan-e1", map[string]string{
		"cla.edu/tenant-id":  "tenant_dev",
		"cla.edu/attempt-id": "a_orphan",
		"cla.edu/epoch":      "1",
	}, time.Date(2026, 6, 24, 9, 0, 0, 0, time.UTC))
	reconciler, _ := newTestReconciler(t, defaultLabSession(), orphan)
	reconciler.Metrics = metrics

	if _, err := (OrphanScanner{Reconciler: reconciler, GracePeriod: 10 * time.Minute}).RunOnce(ctx); err != nil {
		t.Fatalf("cleanup orphans: %v", err)
	}
	if value := metricValue(t, registry, "cla_environment_controller_orphan_namespaces"); value != 1 {
		t.Fatalf("orphan namespaces = %f", value)
	}
	if count := metricHistogramCount(t, registry, "cla_environment_controller_orphan_cleanup_duration_seconds"); count != 1 {
		t.Fatalf("orphan cleanup duration samples = %d", count)
	}
}

func TestOrphanScannerRequiresReconciler(t *testing.T) {
	if _, err := (OrphanScanner{}).RunOnce(context.Background()); err == nil {
		t.Fatalf("expected missing reconciler error")
	}
}

func metricValue(t *testing.T, gatherer prometheus.Gatherer, name string) float64 {
	t.Helper()
	families, err := gatherer.Gather()
	if err != nil {
		t.Fatalf("gather metrics: %v", err)
	}
	for _, family := range families {
		if family.GetName() != name || len(family.Metric) == 0 {
			continue
		}
		metric := family.Metric[0]
		if metric.GetGauge() != nil {
			return metric.GetGauge().GetValue()
		}
		if metric.GetCounter() != nil {
			return metric.GetCounter().GetValue()
		}
		t.Fatalf("metric %s is not gauge or counter", name)
	}
	t.Fatalf("metric %s not found", name)
	return 0
}

func metricHistogramCount(t *testing.T, gatherer prometheus.Gatherer, name string) uint64 {
	t.Helper()
	families, err := gatherer.Gather()
	if err != nil {
		t.Fatalf("gather metrics: %v", err)
	}
	for _, family := range families {
		if family.GetName() == name && len(family.Metric) > 0 && family.Metric[0].GetHistogram() != nil {
			return family.Metric[0].GetHistogram().GetSampleCount()
		}
	}
	t.Fatalf("histogram %s not found", name)
	return 0
}

func metricHistogramSum(t *testing.T, gatherer prometheus.Gatherer, name string) float64 {
	t.Helper()
	families, err := gatherer.Gather()
	if err != nil {
		t.Fatalf("gather metrics: %v", err)
	}
	for _, family := range families {
		if family.GetName() == name && len(family.Metric) > 0 && family.Metric[0].GetHistogram() != nil {
			return family.Metric[0].GetHistogram().GetSampleSum()
		}
	}
	t.Fatalf("histogram %s not found", name)
	return 0
}

func newTestReconciler(t *testing.T, objects ...client.Object) (*Reconciler, client.Client) {
	t.Helper()
	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := appsv1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := cla.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(objects...).
		WithStatusSubresource(&cla.LabSession{}, &appsv1.Deployment{}).
		Build()
	return &Reconciler{
		Client: c,
		Scheme: scheme,
		Secrets: labplan.SecretSet{
			TargetSessionKey: "session-secret",
		},
		Now: func() time.Time {
			return time.Date(2026, 6, 24, 10, 0, 0, 0, time.UTC)
		},
	}, c
}

func defaultLabSession() *cla.LabSession {
	return &cla.LabSession{
		TypeMeta: metav1.TypeMeta{
			APIVersion: cla.SchemeGroupVersion.String(),
			Kind:       "LabSession",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:       "lab-a-123-e2",
			Namespace:  "cla-control",
			Generation: 1,
			CreationTimestamp: metav1.Time{
				Time: time.Date(2026, 6, 24, 9, 0, 0, 0, time.UTC),
			},
		},
		Spec: cla.LabSessionSpec{
			TenantID:         "tenant_dev",
			AttemptID:        "a_123",
			Epoch:            2,
			WorkspaceType:    cla.WorkspaceTerminal,
			RuntimeClassName: "gvisor",
			TTLSeconds:       5400,
			RouteRef:         "route_123",
		},
	}
}

func labNamespace(name string, labels map[string]string, createdAt time.Time) *corev1.Namespace {
	return &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name:   name,
			Labels: labels,
			CreationTimestamp: metav1.Time{
				Time: createdAt,
			},
		},
	}
}

func controlKey() types.NamespacedName {
	return types.NamespacedName{Name: "lab-a-123-e2", Namespace: "cla-control"}
}

func getUnstructured(t *testing.T, c client.Client, apiVersion, kind string, key types.NamespacedName) unstructured.Unstructured {
	t.Helper()
	var object unstructured.Unstructured
	object.SetAPIVersion(apiVersion)
	object.SetKind(kind)
	if err := c.Get(context.Background(), key, &object); err != nil {
		t.Fatalf("missing %s %s: %v", kind, key.String(), err)
	}
	return object
}

func setDeploymentReady(t *testing.T, c client.Client, namespace, name string) {
	t.Helper()
	var deploy appsv1.Deployment
	if err := c.Get(context.Background(), types.NamespacedName{Name: name, Namespace: namespace}, &deploy); err != nil {
		t.Fatalf("missing deployment %s/%s: %v", namespace, name, err)
	}
	deploy.Status.ReadyReplicas = 1
	if err := c.Status().Update(context.Background(), &deploy); err != nil {
		t.Fatal(err)
	}
}

func setDeploymentFailed(t *testing.T, c client.Client, namespace, name, reason, message string) {
	t.Helper()
	var deploy appsv1.Deployment
	if err := c.Get(context.Background(), types.NamespacedName{Name: name, Namespace: namespace}, &deploy); err != nil {
		t.Fatalf("missing deployment %s/%s: %v", namespace, name, err)
	}
	deploy.Status.Conditions = []appsv1.DeploymentCondition{{
		Type:    appsv1.DeploymentProgressing,
		Status:  corev1.ConditionFalse,
		Reason:  reason,
		Message: message,
	}}
	if err := c.Status().Update(context.Background(), &deploy); err != nil {
		t.Fatal(err)
	}
}

func mustGetSession(t *testing.T, c client.Client) *cla.LabSession {
	t.Helper()
	var session cla.LabSession
	if err := c.Get(context.Background(), controlKey(), &session); err != nil {
		t.Fatal(err)
	}
	return &session
}

func assertNamespaceExists(t *testing.T, c client.Client, name string) {
	t.Helper()
	var ns corev1.Namespace
	if err := c.Get(context.Background(), types.NamespacedName{Name: name}, &ns); err != nil {
		t.Fatalf("namespace %s should exist: %v", name, err)
	}
}

func assertNamespaceMissing(t *testing.T, c client.Client, name string) {
	t.Helper()
	var ns corev1.Namespace
	err := c.Get(context.Background(), types.NamespacedName{Name: name}, &ns)
	if !apierrors.IsNotFound(err) {
		t.Fatalf("namespace %s should be deleted, got err=%v", name, err)
	}
}

func hasFinalizer(finalizers []string, expected string) bool {
	for _, finalizer := range finalizers {
		if finalizer == expected {
			return true
		}
	}
	return false
}

type failingEventSink struct{}

func (failingEventSink) EmitLabStatus(context.Context, LabStatusEvent) error {
	return errors.New("control plane unavailable")
}

type recordingRouteRegistry struct {
	registeredAttemptID  string
	registeredEpoch      int
	registered           labcontroller.RouteRegistration
	unregisteredRouteRef string
	revokedAttemptID     string
	revokedEpoch         int
	revokedRouteRef      string
}

func (r *recordingRouteRegistry) RegisterRoute(_ context.Context, attemptID string, epoch int, route labcontroller.RouteRegistration) error {
	r.registeredAttemptID = attemptID
	r.registeredEpoch = epoch
	r.registered = route
	return nil
}

func (r *recordingRouteRegistry) UnregisterRoute(_ context.Context, _ string, _ int, routeRef string) error {
	r.unregisteredRouteRef = routeRef
	return nil
}

func (r *recordingRouteRegistry) RevokeTickets(_ context.Context, attemptID string, epoch int, routeRef string) error {
	r.revokedAttemptID = attemptID
	r.revokedEpoch = epoch
	r.revokedRouteRef = routeRef
	return nil
}

type failingRouteRegistry struct{}

func (failingRouteRegistry) RegisterRoute(context.Context, string, int, labcontroller.RouteRegistration) error {
	return errors.New("route registry unavailable")
}

func (failingRouteRegistry) UnregisterRoute(context.Context, string, int, string) error {
	return errors.New("route registry unavailable")
}

func (failingRouteRegistry) RevokeTickets(context.Context, string, int, string) error {
	return errors.New("ticket revocation unavailable")
}
