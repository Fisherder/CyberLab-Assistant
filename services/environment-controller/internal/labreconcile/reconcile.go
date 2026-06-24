package labreconcile

import (
	"sort"
	"time"

	cla "cla-platform/services/environment-controller/api/v1"
	"cla-platform/services/environment-controller/internal/labplan"
)

const (
	FinalizerName     = "cla.edu/labsession-finalizer"
	DefaultTTLSeconds = 5400
)

type ActionType string

const (
	ActionAddFinalizer       ActionType = "AddFinalizer"
	ActionApplyResources     ActionType = "ApplyResources"
	ActionPollHealth         ActionType = "PollHealth"
	ActionRegisterRoute      ActionType = "RegisterRoute"
	ActionEmitStatusEvent    ActionType = "EmitStatusEvent"
	ActionRecordFailure      ActionType = "RecordFailure"
	ActionExpireSession      ActionType = "ExpireSession"
	ActionRevokeTickets      ActionType = "RevokeTickets"
	ActionUnregisterRoute    ActionType = "UnregisterRoute"
	ActionDeleteNamespace    ActionType = "DeleteNamespace"
	ActionVerifyNoResiduals  ActionType = "VerifyNoResidualResources"
	ActionRemoveFinalizer    ActionType = "RemoveFinalizer"
	ActionCleanupOrphan      ActionType = "CleanupOrphanNamespace"
	ActionVerifyOrphanDelete ActionType = "VerifyOrphanNamespaceDeleted"
)

type Metadata struct {
	Name         string
	CreatedAt    time.Time
	DeletedAt    *time.Time
	Finalizers   []string
	Generation   int64
	LastObserved int64
}

type ResourceState struct {
	NamespaceExists bool
	ResourcesSynced bool
	WorkspaceReady  bool
	TargetReady     bool
	OracleReady     bool
	RouteRegistered bool
	CleanupComplete bool
	Failed          map[string]string
}

type Input struct {
	Spec      cla.LabSessionSpec
	Metadata  Metadata
	Resources ResourceState
	Now       time.Time
}

type Action struct {
	Type   ActionType
	Target string
	Reason string
}

type Decision struct {
	Actions      []Action
	Status       cla.LabSessionStatus
	Finalizers   []string
	RequeueAfter time.Duration
}

type NamespaceRef struct {
	Name      string
	Labels    map[string]string
	CreatedAt time.Time
}

type OrphanScanInput struct {
	Now              time.Time
	ActiveNamespaces map[string]bool
	Namespaces       []NamespaceRef
	GracePeriod      time.Duration
}

func Reconcile(input Input) Decision {
	now := normalizeTime(input.Now)
	createdAt := normalizeTime(input.Metadata.CreatedAt)
	spec := input.Spec
	namespace := ""
	if spec.AttemptID != "" && spec.Epoch > 0 {
		namespace = labplan.NamespaceName(spec)
	}
	status := cla.LabSessionStatus{
		Phase:              string(cla.SessionProvisioning),
		ObservedGeneration: input.Metadata.Generation,
		NamespaceName:      namespace,
		RouteReady:         input.Resources.RouteRegistered,
		Components:         components(input.Resources),
		ExpiresAt:          expiresAt(createdAt, spec.TTLSeconds).Format(time.RFC3339),
	}

	if input.Metadata.DeletedAt != nil {
		return finalizingDecision(input, status)
	}

	if err := validateSpec(spec); err != nil {
		status.Phase = string(cla.SessionFailed)
		status.RouteReady = false
		status.Reason = "InvalidSpec"
		status.Conditions = []cla.LabSessionCondition{{
			Type:    "SpecValid",
			Status:  "False",
			Reason:  "InvalidSpec",
			Message: err.Error(),
		}}
		return Decision{
			Actions: []Action{{
				Type:   ActionRecordFailure,
				Target: input.Metadata.Name,
				Reason: err.Error(),
			}},
			Status:     status,
			Finalizers: cloneFinalizers(input.Metadata.Finalizers),
		}
	}

	decision := Decision{
		Status:     status,
		Finalizers: ensureFinalizer(input.Metadata.Finalizers),
	}
	if !hasFinalizer(input.Metadata.Finalizers) {
		decision.Actions = append(decision.Actions, Action{
			Type:   ActionAddFinalizer,
			Target: input.Metadata.Name,
			Reason: "cleanup must revoke route, tickets, and namespace before LabSession removal",
		})
	}

	if now.After(expiresAt(createdAt, spec.TTLSeconds)) || now.Equal(expiresAt(createdAt, spec.TTLSeconds)) {
		decision.Status.Phase = string(cla.SessionExpired)
		decision.Status.RouteReady = false
		decision.Status.Reason = "TTLExpired"
		decision.Status.Conditions = []cla.LabSessionCondition{{Type: "TTL", Status: "False", Reason: "Expired"}}
		decision.Actions = append(decision.Actions,
			Action{Type: ActionExpireSession, Target: input.Metadata.Name, Reason: "ttl elapsed"},
			Action{Type: ActionRevokeTickets, Target: spec.RouteRef, Reason: "ttl elapsed"},
			Action{Type: ActionUnregisterRoute, Target: spec.RouteRef, Reason: "ttl elapsed"},
			Action{Type: ActionDeleteNamespace, Target: namespace, Reason: "ttl elapsed"},
			Action{Type: ActionEmitStatusEvent, Target: input.Metadata.Name, Reason: "expired"},
		)
		return decision
	}

	if len(input.Resources.Failed) > 0 {
		decision.Status.Phase = string(cla.SessionFailed)
		decision.Status.RouteReady = false
		decision.Status.Reason = "ComponentFailed"
		decision.Status.Conditions = failureConditions(input.Resources.Failed)
		decision.Actions = append(decision.Actions,
			Action{Type: ActionRecordFailure, Target: input.Metadata.Name, Reason: "component failed"},
			Action{Type: ActionRevokeTickets, Target: spec.RouteRef, Reason: "component failed"},
			Action{Type: ActionUnregisterRoute, Target: spec.RouteRef, Reason: "component failed"},
			Action{Type: ActionEmitStatusEvent, Target: input.Metadata.Name, Reason: "failed"},
		)
		return decision
	}

	if !input.Resources.NamespaceExists || !input.Resources.ResourcesSynced {
		decision.Status.Phase = string(cla.SessionPending)
		decision.Status.RouteReady = false
		decision.Status.Conditions = []cla.LabSessionCondition{{Type: "ResourcesCreated", Status: "False", Reason: "ApplyPending"}}
		decision.RequeueAfter = 2 * time.Second
		decision.Actions = append(decision.Actions,
			Action{Type: ActionApplyResources, Target: namespace, Reason: "namespace or topology missing"},
			Action{Type: ActionEmitStatusEvent, Target: input.Metadata.Name, Reason: "pending"},
		)
		return decision
	}

	if !allComponentsReady(input.Resources) {
		decision.Status.Phase = string(cla.SessionProvisioning)
		decision.Status.RouteReady = false
		decision.Status.Conditions = []cla.LabSessionCondition{{Type: "ComponentsReady", Status: "False", Reason: "HealthPending"}}
		decision.RequeueAfter = 5 * time.Second
		decision.Actions = append(decision.Actions, Action{Type: ActionPollHealth, Target: namespace, Reason: "components not ready"})
		return decision
	}

	if !input.Resources.RouteRegistered {
		decision.Status.Phase = string(cla.SessionProvisioning)
		decision.Status.RouteReady = false
		decision.Status.Conditions = []cla.LabSessionCondition{{Type: "RouteRegistered", Status: "False", Reason: "RoutePending"}}
		decision.RequeueAfter = time.Second
		decision.Actions = append(decision.Actions,
			Action{Type: ActionRegisterRoute, Target: spec.RouteRef, Reason: "components ready"},
			Action{Type: ActionEmitStatusEvent, Target: input.Metadata.Name, Reason: "route pending"},
		)
		return decision
	}

	decision.Status.Phase = string(cla.SessionReady)
	decision.Status.RouteReady = true
	decision.Status.Conditions = []cla.LabSessionCondition{
		{Type: "ResourcesCreated", Status: "True", Reason: "Reconciled"},
		{Type: "ComponentsReady", Status: "True", Reason: "HealthChecksPassed"},
		{Type: "RouteRegistered", Status: "True", Reason: "RouteReady"},
	}
	decision.RequeueAfter = expiresAt(createdAt, spec.TTLSeconds).Sub(now)
	if decision.RequeueAfter < 0 {
		decision.RequeueAfter = 0
	}
	return decision
}

func PlanOrphanCleanup(input OrphanScanInput) []Action {
	now := normalizeTime(input.Now)
	active := input.ActiveNamespaces
	if active == nil {
		active = map[string]bool{}
	}
	var actions []Action
	for _, namespace := range input.Namespaces {
		if !isLabNamespace(namespace) || active[namespace.Name] {
			continue
		}
		if input.GracePeriod > 0 && now.Sub(namespace.CreatedAt) < input.GracePeriod {
			continue
		}
		actions = append(actions,
			Action{Type: ActionCleanupOrphan, Target: namespace.Name, Reason: "no active LabSession owns namespace"},
			Action{Type: ActionVerifyOrphanDelete, Target: namespace.Name, Reason: "orphan cleanup verification"},
		)
	}
	sort.Slice(actions, func(i, j int) bool {
		if actions[i].Target == actions[j].Target {
			return actions[i].Type < actions[j].Type
		}
		return actions[i].Target < actions[j].Target
	})
	return actions
}

func finalizingDecision(input Input, status cla.LabSessionStatus) Decision {
	namespace := status.NamespaceName
	status.Phase = string(cla.SessionTerminating)
	status.RouteReady = false
	status.Reason = "Deleting"
	status.Conditions = []cla.LabSessionCondition{{Type: "Finalizing", Status: "True", Reason: "DeletionRequested"}}
	decision := Decision{
		Status:     status,
		Finalizers: cloneFinalizers(input.Metadata.Finalizers),
		Actions: []Action{
			{Type: ActionRevokeTickets, Target: input.Spec.RouteRef, Reason: "labsession deleting"},
			{Type: ActionUnregisterRoute, Target: input.Spec.RouteRef, Reason: "labsession deleting"},
			{Type: ActionDeleteNamespace, Target: namespace, Reason: "labsession deleting"},
			{Type: ActionVerifyNoResiduals, Target: namespace, Reason: "labsession deleting"},
			{Type: ActionEmitStatusEvent, Target: input.Metadata.Name, Reason: "terminating"},
		},
		RequeueAfter: 3 * time.Second,
	}
	if input.Resources.CleanupComplete {
		decision.Finalizers = removeFinalizer(decision.Finalizers)
		decision.Actions = append(decision.Actions, Action{
			Type:   ActionRemoveFinalizer,
			Target: input.Metadata.Name,
			Reason: "namespace and route cleanup verified",
		})
		decision.RequeueAfter = 0
	}
	return decision
}

func validateSpec(spec cla.LabSessionSpec) error {
	_, err := labplan.Plan(spec, labplan.ImageSet{}, labplan.SecretSet{TargetSessionKey: "redacted-controller-secret"})
	return err
}

func components(resources ResourceState) map[string]cla.ComponentPhase {
	out := map[string]cla.ComponentPhase{
		"workspace":   componentPhase(resources.WorkspaceReady),
		"target":      componentPhase(resources.TargetReady),
		"oracleProbe": componentPhase(resources.OracleReady),
	}
	for name := range resources.Failed {
		out[name] = cla.ComponentFailed
	}
	return out
}

func componentPhase(ready bool) cla.ComponentPhase {
	if ready {
		return cla.ComponentReady
	}
	return cla.ComponentPending
}

func allComponentsReady(resources ResourceState) bool {
	return resources.WorkspaceReady && resources.TargetReady && resources.OracleReady
}

func failureConditions(failed map[string]string) []cla.LabSessionCondition {
	names := make([]string, 0, len(failed))
	for name := range failed {
		names = append(names, name)
	}
	sort.Strings(names)
	conditions := make([]cla.LabSessionCondition, 0, len(names))
	for _, name := range names {
		conditions = append(conditions, cla.LabSessionCondition{
			Type:    "ComponentReady",
			Status:  "False",
			Reason:  "ComponentFailed",
			Message: name + ": " + failed[name],
		})
	}
	return conditions
}

func expiresAt(createdAt time.Time, ttlSeconds int) time.Time {
	if ttlSeconds <= 0 {
		ttlSeconds = DefaultTTLSeconds
	}
	return createdAt.Add(time.Duration(ttlSeconds) * time.Second).UTC()
}

func normalizeTime(value time.Time) time.Time {
	if value.IsZero() {
		return time.Now().UTC()
	}
	return value.UTC()
}

func ensureFinalizer(finalizers []string) []string {
	out := cloneFinalizers(finalizers)
	if !hasFinalizer(out) {
		out = append(out, FinalizerName)
	}
	return out
}

func hasFinalizer(finalizers []string) bool {
	for _, finalizer := range finalizers {
		if finalizer == FinalizerName {
			return true
		}
	}
	return false
}

func removeFinalizer(finalizers []string) []string {
	out := finalizers[:0]
	for _, finalizer := range finalizers {
		if finalizer != FinalizerName {
			out = append(out, finalizer)
		}
	}
	return cloneFinalizers(out)
}

func cloneFinalizers(finalizers []string) []string {
	if len(finalizers) == 0 {
		return nil
	}
	out := make([]string, len(finalizers))
	copy(out, finalizers)
	return out
}

func isLabNamespace(namespace NamespaceRef) bool {
	if namespace.Name == "" {
		return false
	}
	if namespace.Labels["cla.edu/attempt-id"] == "" || namespace.Labels["cla.edu/epoch"] == "" {
		return false
	}
	return true
}
