package k8scontroller

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labcontroller"
	"cla-platform/services/environment-controller/internal/labplan"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

const (
	routeRegisteredAnnotation = "cla.edu/route-registered"
	lastRouteErrorAnnotation  = "cla.edu/last-route-error"
	lastEventErrorAnnotation  = "cla.edu/last-event-error"
)

type Reconciler struct {
	client.Client
	Scheme   *runtime.Scheme
	Images   labplan.ImageSet
	Secrets  labplan.SecretSet
	Routes   RouteRegistry
	Events   EventSink
	Recorder record.EventRecorder
	Metrics  *Metrics
	Now      func() time.Time
}

func (r *Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	var session cla.LabSession
	if err := r.Get(ctx, req.NamespacedName, &session); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		if r.Metrics != nil {
			r.Metrics.ObserveReconcileError()
		}
		return ctrl.Result{}, err
	}
	return r.ReconcileLabSession(ctx, &session)
}

func (r *Reconciler) ReconcileLabSession(ctx context.Context, session *cla.LabSession) (ctrl.Result, error) {
	store := &Store{
		Client:           r.Client,
		ControlNamespace: session.Namespace,
		LabSessionName:   session.Name,
		Images:           r.Images,
		Spec:             session.Spec,
		Routes:           r.Routes,
		Events:           r.Events,
		Recorder:         r.Recorder,
	}
	now := time.Now().UTC()
	if r.Now != nil {
		now = r.Now().UTC()
	}
	var deletedAt *time.Time
	if session.DeletionTimestamp != nil {
		value := session.DeletionTimestamp.Time
		deletedAt = &value
	}
	decision, err := labcontroller.Reconciler{
		Store:        store,
		SecretSource: labcontroller.StaticSecretProvider{Secrets: r.Secrets},
		Images:       r.Images,
	}.Reconcile(ctx, labreconcile.Input{
		Spec: session.Spec,
		Metadata: labreconcile.Metadata{
			Name:         session.Name,
			CreatedAt:    session.CreationTimestamp.Time,
			DeletedAt:    deletedAt,
			Finalizers:   append([]string(nil), session.Finalizers...),
			Generation:   session.Generation,
			LastObserved: observedGeneration(session),
		},
		Resources: store.ResourceState(ctx, session),
		Now:       now,
	})
	if err != nil {
		if r.Metrics != nil {
			r.Metrics.ObserveReconcileError()
		}
		return ctrl.Result{}, err
	}
	if r.Metrics != nil {
		r.Metrics.ObserveReconcileSuccess(session, decision, now)
	}
	return ctrl.Result{RequeueAfter: decision.RequeueAfter}, nil
}

func (r *Reconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).For(&cla.LabSession{}).Complete(r)
}

type Store struct {
	client.Client
	ControlNamespace string
	LabSessionName   string
	Images           labplan.ImageSet
	Spec             cla.LabSessionSpec
	Routes           RouteRegistry
	Events           EventSink
	Recorder         record.EventRecorder
}

func (s *Store) PatchFinalizers(ctx context.Context, name string, finalizers []string) error {
	var session cla.LabSession
	if err := s.Get(ctx, types.NamespacedName{Name: name, Namespace: s.ControlNamespace}, &session); err != nil {
		return err
	}
	session.Finalizers = append([]string(nil), finalizers...)
	return s.Update(ctx, &session)
}

func (s *Store) PatchStatus(ctx context.Context, name string, status cla.LabSessionStatus) error {
	var session cla.LabSession
	if err := s.Get(ctx, types.NamespacedName{Name: name, Namespace: s.ControlNamespace}, &session); err != nil {
		return err
	}
	session.Status = status
	return s.Status().Update(ctx, &session)
}

func (s *Store) ApplyResources(ctx context.Context, _ string, objects []labplan.Object) error {
	for _, object := range objects {
		desired, err := toUnstructured(object)
		if err != nil {
			return err
		}
		key := types.NamespacedName{Name: desired.GetName(), Namespace: desired.GetNamespace()}
		var existing unstructured.Unstructured
		existing.SetAPIVersion(desired.GetAPIVersion())
		existing.SetKind(desired.GetKind())
		if err := s.Get(ctx, key, &existing); err != nil {
			if apierrors.IsNotFound(err) {
				if err := s.Create(ctx, desired); err != nil {
					return err
				}
				continue
			}
			return err
		}
		existing.SetLabels(desired.GetLabels())
		for key, value := range desired.Object {
			if key == "apiVersion" || key == "kind" || key == "metadata" || key == "status" {
				continue
			}
			existing.Object[key] = value
		}
		if err := s.Update(ctx, &existing); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) PollHealth(context.Context, string) error {
	return nil
}

func (s *Store) RegisterRoute(ctx context.Context, route labcontroller.RouteRegistration) error {
	if s.Routes != nil {
		if err := s.Routes.RegisterRoute(ctx, s.Spec.AttemptID, s.Spec.Epoch, route); err != nil {
			_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, truncateAnnotation(err.Error()))
			return err
		}
		_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, "")
	}
	return s.patchLabSessionAnnotation(ctx, routeRegisteredAnnotation, route.RouteRef)
}

func (s *Store) UnregisterRoute(ctx context.Context, routeRef string) error {
	if s.Routes != nil {
		if err := s.Routes.UnregisterRoute(ctx, s.Spec.AttemptID, s.Spec.Epoch, routeRef); err != nil {
			_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, truncateAnnotation(err.Error()))
			return err
		}
		_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, "")
	}
	return s.patchLabSessionAnnotation(ctx, routeRegisteredAnnotation, "")
}

func (s *Store) RevokeTickets(ctx context.Context, routeRef string) error {
	if s.Routes == nil {
		return nil
	}
	if err := s.Routes.RevokeTickets(ctx, s.Spec.AttemptID, s.Spec.Epoch, routeRef); err != nil {
		_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, truncateAnnotation(err.Error()))
		return err
	}
	_ = s.patchLabSessionAnnotation(ctx, lastRouteErrorAnnotation, "")
	return nil
}

func (s *Store) DeleteNamespace(ctx context.Context, namespace string) error {
	if namespace == "" {
		return nil
	}
	var ns corev1.Namespace
	if err := s.Get(ctx, types.NamespacedName{Name: namespace}, &ns); err != nil {
		if apierrors.IsNotFound(err) {
			return nil
		}
		return err
	}
	return s.Delete(ctx, &ns)
}

func (s *Store) VerifyNoResidualResources(ctx context.Context, namespace string) error {
	var ns corev1.Namespace
	if err := s.Get(ctx, types.NamespacedName{Name: namespace}, &ns); err != nil {
		if apierrors.IsNotFound(err) {
			return nil
		}
		return err
	}
	return fmt.Errorf("namespace %s still exists", namespace)
}

func (s *Store) ExpireSession(ctx context.Context, name string, reason string) error {
	return s.patchLabSessionAnnotation(ctx, "cla.edu/expire-reason", reason)
}

func (s *Store) EmitStatusEvent(ctx context.Context, name string, status cla.LabSessionStatus, reason string) error {
	s.recordKubernetesStatusEvent(ctx, name, status, reason)
	if s.Events != nil {
		err := s.Events.EmitLabStatus(ctx, LabStatusEvent{
			TenantID:        s.Spec.TenantID,
			AttemptID:       s.Spec.AttemptID,
			SessionEpoch:    s.Spec.Epoch,
			LabSessionName:  name,
			Status:          status,
			ReconcileReason: reason,
		})
		if err != nil {
			_ = s.patchLabSessionAnnotation(ctx, lastEventErrorAnnotation, truncateAnnotation(err.Error()))
			return nil
		}
		_ = s.patchLabSessionAnnotation(ctx, lastEventErrorAnnotation, "")
	}
	return nil
}

func (s *Store) recordKubernetesStatusEvent(ctx context.Context, name string, status cla.LabSessionStatus, reconcileReason string) {
	if s.Recorder == nil {
		return
	}
	var session cla.LabSession
	if err := s.Get(ctx, types.NamespacedName{Name: name, Namespace: s.ControlNamespace}, &session); err != nil {
		return
	}
	eventType := corev1.EventTypeNormal
	if status.Phase == string(cla.SessionFailed) || status.Phase == string(cla.SessionExpired) {
		eventType = corev1.EventTypeWarning
	}
	s.Recorder.Eventf(
		&session,
		eventType,
		kubernetesStatusEventReason(status, reconcileReason),
		"LabSession %s phase=%s routeReady=%t reconcileReason=%s",
		name,
		status.Phase,
		status.RouteReady,
		reconcileReason,
	)
}

func kubernetesStatusEventReason(status cla.LabSessionStatus, reconcileReason string) string {
	switch reconcileReason {
	case "pending":
		return "LabSessionPending"
	case "route pending":
		return "LabSessionRoutePending"
	case "expired":
		return "LabSessionExpired"
	case "failed":
		return "LabSessionFailed"
	case "terminating":
		return "LabSessionTerminating"
	}
	switch status.Phase {
	case string(cla.SessionReady):
		return "LabSessionReady"
	case string(cla.SessionFailed):
		return "LabSessionFailed"
	case string(cla.SessionExpired):
		return "LabSessionExpired"
	case string(cla.SessionTerminating):
		return "LabSessionTerminating"
	case string(cla.SessionPending):
		return "LabSessionPending"
	default:
		return "LabSessionStatusChanged"
	}
}

func (s *Store) RecordFailure(ctx context.Context, name string, reason string) error {
	return s.patchLabSessionAnnotation(ctx, "cla.edu/failure-reason", reason)
}

func (s *Store) ResourceState(ctx context.Context, session *cla.LabSession) labreconcile.ResourceState {
	namespaceName := labplan.NamespaceName(session.Spec)
	state := labreconcile.ResourceState{
		NamespaceExists: namespaceExists(ctx, s.Client, namespaceName),
		RouteRegistered: session.Annotations[routeRegisteredAnnotation] == session.Spec.RouteRef,
	}
	state.ResourcesSynced = state.NamespaceExists && resourcesExist(ctx, s.Client, session.Spec, namespaceName)
	state.WorkspaceReady = deploymentReady(ctx, s.Client, namespaceName, "workspace")
	state.TargetReady = deploymentReady(ctx, s.Client, namespaceName, "target")
	state.OracleReady = state.WorkspaceReady && state.TargetReady
	state.CleanupComplete = !state.NamespaceExists
	state.Failed = deploymentFailures(ctx, s.Client, namespaceName)
	return state
}

func (s *Store) patchLabSessionAnnotation(ctx context.Context, key string, value string) error {
	var session cla.LabSession
	if err := s.Get(ctx, types.NamespacedName{Name: s.LabSessionName, Namespace: s.ControlNamespace}, &session); err != nil {
		return err
	}
	annotations := session.Annotations
	if annotations == nil {
		annotations = map[string]string{}
	}
	if value == "" {
		delete(annotations, key)
	} else {
		annotations[key] = value
	}
	session.Annotations = annotations
	return s.Update(ctx, &session)
}

func namespaceExists(ctx context.Context, c client.Client, name string) bool {
	var ns corev1.Namespace
	return c.Get(ctx, types.NamespacedName{Name: name}, &ns) == nil
}

func resourcesExist(ctx context.Context, c client.Client, spec cla.LabSessionSpec, namespace string) bool {
	objects, err := labplan.Plan(spec, labplan.ImageSet{}, labplan.SecretSet{TargetSessionKey: "redacted-controller-secret"})
	if err != nil {
		return false
	}
	for _, object := range objects {
		desired, err := toUnstructured(object)
		if err != nil {
			return false
		}
		var existing unstructured.Unstructured
		existing.SetAPIVersion(desired.GetAPIVersion())
		existing.SetKind(desired.GetKind())
		if err := c.Get(ctx, types.NamespacedName{Name: desired.GetName(), Namespace: desired.GetNamespace()}, &existing); err != nil {
			return false
		}
	}
	return namespace != ""
}

func deploymentReady(ctx context.Context, c client.Client, namespace, name string) bool {
	var deploy appsv1.Deployment
	if err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, &deploy); err != nil {
		return false
	}
	replicas := int32(1)
	if deploy.Spec.Replicas != nil {
		replicas = *deploy.Spec.Replicas
	}
	return deploy.Status.ReadyReplicas >= replicas
}

func deploymentFailures(ctx context.Context, c client.Client, namespace string) map[string]string {
	failed := map[string]string{}
	for _, name := range []string{"workspace", "target"} {
		var deploy appsv1.Deployment
		if err := c.Get(ctx, types.NamespacedName{Name: name, Namespace: namespace}, &deploy); err != nil {
			continue
		}
		if reason := deploymentFailureReason(deploy); reason != "" {
			failed[name] = reason
		}
	}
	if len(failed) == 0 {
		return nil
	}
	return failed
}

func deploymentFailureReason(deploy appsv1.Deployment) string {
	for _, condition := range deploy.Status.Conditions {
		switch {
		case condition.Type == appsv1.DeploymentReplicaFailure && condition.Status == corev1.ConditionTrue:
			return conditionReasonMessage(condition)
		case condition.Type == appsv1.DeploymentProgressing && condition.Status == corev1.ConditionFalse:
			return conditionReasonMessage(condition)
		}
	}
	return ""
}

func conditionReasonMessage(condition appsv1.DeploymentCondition) string {
	if condition.Reason == "" {
		return condition.Message
	}
	if condition.Message == "" {
		return condition.Reason
	}
	return condition.Reason + ": " + condition.Message
}

func toUnstructured(object labplan.Object) (*unstructured.Unstructured, error) {
	if object.APIVersion == "" || object.Kind == "" || object.Metadata.Name == "" {
		return nil, fmt.Errorf("invalid planned object %#v", object.Metadata)
	}
	out := &unstructured.Unstructured{Object: map[string]any{}}
	out.SetAPIVersion(object.APIVersion)
	out.SetKind(object.Kind)
	out.SetName(object.Metadata.Name)
	out.SetNamespace(object.Metadata.Namespace)
	out.SetLabels(object.Metadata.Labels)
	if object.Kind == "Secret" {
		if value, ok := object.Spec["type"]; ok {
			out.Object["type"] = value
		}
		if object.StringData != nil {
			data := map[string]any{}
			for key, value := range object.StringData {
				data[key] = value
			}
			out.Object["stringData"] = data
		}
		return out, nil
	}
	if len(object.Spec) > 0 {
		out.Object["spec"] = normalize(object.Spec)
	}
	return out, nil
}

func normalize(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		out := map[string]any{}
		for key, value := range typed {
			out[key] = normalize(value)
		}
		return out
	case map[string]string:
		out := map[string]any{}
		for key, value := range typed {
			out[key] = value
		}
		return out
	case []map[string]any:
		out := make([]any, len(typed))
		for i, value := range typed {
			out[i] = normalize(value)
		}
		return out
	case []map[string]string:
		out := make([]any, len(typed))
		for i, value := range typed {
			out[i] = normalize(value)
		}
		return out
	case []string:
		out := make([]any, len(typed))
		for i, value := range typed {
			out[i] = value
		}
		return out
	default:
		return typed
	}
}

func observedGeneration(session *cla.LabSession) int64 {
	return session.Status.ObservedGeneration
}

func truncateAnnotation(value string) string {
	const maxAnnotationValue = 240
	if len(value) <= maxAnnotationValue {
		return value
	}
	return value[:maxAnnotationValue]
}
