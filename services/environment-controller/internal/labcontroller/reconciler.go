package labcontroller

import (
	"context"
	"fmt"
	"reflect"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labplan"
	"cla-platform/services/environment-controller/internal/labreconcile"
)

const (
	WorkspaceServiceName = "workspace-sessiond"
	SessiondPort         = 7777
)

type Store interface {
	PatchFinalizers(ctx context.Context, name string, finalizers []string) error
	PatchStatus(ctx context.Context, name string, status cla.LabSessionStatus) error
	ApplyResources(ctx context.Context, namespace string, objects []labplan.Object) error
	PollHealth(ctx context.Context, namespace string) error
	RegisterRoute(ctx context.Context, route RouteRegistration) error
	UnregisterRoute(ctx context.Context, routeRef string) error
	RevokeTickets(ctx context.Context, routeRef string) error
	DeleteNamespace(ctx context.Context, namespace string) error
	VerifyNoResidualResources(ctx context.Context, namespace string) error
	ExpireSession(ctx context.Context, name string, reason string) error
	EmitStatusEvent(ctx context.Context, name string, status cla.LabSessionStatus, reason string) error
	RecordFailure(ctx context.Context, name string, reason string) error
}

type SecretProvider interface {
	SecretsFor(ctx context.Context, spec cla.LabSessionSpec) (labplan.SecretSet, error)
}

type StaticSecretProvider struct {
	Secrets labplan.SecretSet
}

type RouteRegistration struct {
	RouteRef    string
	Namespace   string
	ServiceName string
	Port        int
}

type Reconciler struct {
	Store        Store
	SecretSource SecretProvider
	Images       labplan.ImageSet
}

func (r Reconciler) Reconcile(ctx context.Context, input labreconcile.Input) (labreconcile.Decision, error) {
	if r.Store == nil {
		return labreconcile.Decision{}, fmt.Errorf("store is required")
	}
	decision := labreconcile.Reconcile(input)
	if !reflect.DeepEqual(input.Metadata.Finalizers, decision.Finalizers) {
		if err := r.Store.PatchFinalizers(ctx, input.Metadata.Name, decision.Finalizers); err != nil {
			return decision, err
		}
	}
	for _, action := range decision.Actions {
		if err := r.executeAction(ctx, input, decision, action); err != nil {
			return decision, err
		}
	}
	if err := r.Store.PatchStatus(ctx, input.Metadata.Name, decision.Status); err != nil {
		return decision, err
	}
	return decision, nil
}

func (r Reconciler) CleanupOrphans(ctx context.Context, input labreconcile.OrphanScanInput) ([]labreconcile.Action, error) {
	if r.Store == nil {
		return nil, fmt.Errorf("store is required")
	}
	actions := labreconcile.PlanOrphanCleanup(input)
	for _, action := range actions {
		switch action.Type {
		case labreconcile.ActionCleanupOrphan:
			if err := r.Store.DeleteNamespace(ctx, action.Target); err != nil {
				return actions, err
			}
		case labreconcile.ActionVerifyOrphanDelete:
			if err := r.Store.VerifyNoResidualResources(ctx, action.Target); err != nil {
				return actions, err
			}
		}
	}
	return actions, nil
}

func (p StaticSecretProvider) SecretsFor(context.Context, cla.LabSessionSpec) (labplan.SecretSet, error) {
	if p.Secrets.TargetSessionKey == "" {
		return labplan.SecretSet{}, fmt.Errorf("target session key is required")
	}
	return p.Secrets, nil
}

func (r Reconciler) executeAction(ctx context.Context, input labreconcile.Input, decision labreconcile.Decision, action labreconcile.Action) error {
	switch action.Type {
	case labreconcile.ActionAddFinalizer, labreconcile.ActionRemoveFinalizer:
		return nil
	case labreconcile.ActionApplyResources:
		secrets, err := r.secrets(ctx, input.Spec)
		if err != nil {
			return err
		}
		objects, err := labplan.Plan(input.Spec, r.Images, secrets)
		if err != nil {
			return err
		}
		return r.Store.ApplyResources(ctx, decision.Status.NamespaceName, objects)
	case labreconcile.ActionPollHealth:
		return r.Store.PollHealth(ctx, decision.Status.NamespaceName)
	case labreconcile.ActionRegisterRoute:
		return r.Store.RegisterRoute(ctx, RouteRegistration{
			RouteRef:    input.Spec.RouteRef,
			Namespace:   decision.Status.NamespaceName,
			ServiceName: WorkspaceServiceName,
			Port:        SessiondPort,
		})
	case labreconcile.ActionEmitStatusEvent:
		return r.Store.EmitStatusEvent(ctx, input.Metadata.Name, decision.Status, action.Reason)
	case labreconcile.ActionRecordFailure:
		return r.Store.RecordFailure(ctx, input.Metadata.Name, action.Reason)
	case labreconcile.ActionExpireSession:
		return r.Store.ExpireSession(ctx, input.Metadata.Name, action.Reason)
	case labreconcile.ActionRevokeTickets:
		return r.Store.RevokeTickets(ctx, input.Spec.RouteRef)
	case labreconcile.ActionUnregisterRoute:
		return r.Store.UnregisterRoute(ctx, input.Spec.RouteRef)
	case labreconcile.ActionDeleteNamespace:
		return r.Store.DeleteNamespace(ctx, decision.Status.NamespaceName)
	case labreconcile.ActionVerifyNoResiduals:
		return r.Store.VerifyNoResidualResources(ctx, decision.Status.NamespaceName)
	default:
		return fmt.Errorf("unsupported action %s", action.Type)
	}
}

func (r Reconciler) secrets(ctx context.Context, spec cla.LabSessionSpec) (labplan.SecretSet, error) {
	if r.SecretSource == nil {
		return labplan.SecretSet{}, fmt.Errorf("secret source is required")
	}
	return r.SecretSource.SecretsFor(ctx, spec)
}
