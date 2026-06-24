package v1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

const GroupName = "cla.edu"

var SchemeGroupVersion = schema.GroupVersion{Group: GroupName, Version: "v1"}

type ComponentPhase string

type SessionPhase string

type WorkspaceType string

const (
	WorkspaceTerminal      WorkspaceType  = "TERMINAL"
	WorkspaceRemoteDesktop WorkspaceType  = "REMOTE_DESKTOP"
	WorkspaceSimulated     WorkspaceType  = "SIMULATED"
	ComponentPending       ComponentPhase = "Pending"
	ComponentReady         ComponentPhase = "Ready"
	ComponentFailed        ComponentPhase = "Failed"
	SessionPending         SessionPhase   = "Pending"
	SessionProvisioning    SessionPhase   = "Provisioning"
	SessionReady           SessionPhase   = "Ready"
	SessionFailed          SessionPhase   = "Failed"
	SessionExpired         SessionPhase   = "Expired"
	SessionTerminating     SessionPhase   = "Terminating"
)

type LabSessionSpec struct {
	TenantID         string        `json:"tenantId"`
	AttemptID        string        `json:"attemptId"`
	Epoch            int           `json:"epoch"`
	WorkspaceType    WorkspaceType `json:"workspaceType"`
	RuntimeClassName string        `json:"runtimeClassName"`
	TTLSeconds       int           `json:"ttlSeconds"`
	RouteRef         string        `json:"routeRef"`
}

type LabSessionStatus struct {
	Phase              string                    `json:"phase"`
	ObservedGeneration int64                     `json:"observedGeneration,omitempty"`
	NamespaceName      string                    `json:"namespaceName,omitempty"`
	RouteReady         bool                      `json:"routeReady"`
	Components         map[string]ComponentPhase `json:"components,omitempty"`
	ExpiresAt          string                    `json:"expiresAt,omitempty"`
	Conditions         []LabSessionCondition     `json:"conditions,omitempty"`
	Reason             string                    `json:"reason,omitempty"`
}

type LabSessionCondition struct {
	Type    string `json:"type"`
	Status  string `json:"status"`
	Reason  string `json:"reason,omitempty"`
	Message string `json:"message,omitempty"`
}

type LabSession struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   LabSessionSpec   `json:"spec,omitempty"`
	Status LabSessionStatus `json:"status,omitempty"`
}

type LabSessionList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`

	Items []LabSession `json:"items"`
}

func AddToScheme(scheme *runtime.Scheme) error {
	scheme.AddKnownTypes(SchemeGroupVersion, &LabSession{}, &LabSessionList{})
	metav1.AddToGroupVersion(scheme, SchemeGroupVersion)
	return nil
}

func (in *LabSession) DeepCopyObject() runtime.Object {
	if in == nil {
		return nil
	}
	out := new(LabSession)
	*out = *in
	out.ObjectMeta = *in.ObjectMeta.DeepCopy()
	out.Status = deepCopyStatus(in.Status)
	return out
}

func (in *LabSessionList) DeepCopyObject() runtime.Object {
	if in == nil {
		return nil
	}
	out := new(LabSessionList)
	*out = *in
	if in.Items != nil {
		out.Items = make([]LabSession, len(in.Items))
		for i := range in.Items {
			out.Items[i] = *in.Items[i].DeepCopyObject().(*LabSession)
		}
	}
	return out
}

func deepCopyStatus(in LabSessionStatus) LabSessionStatus {
	out := in
	if in.Components != nil {
		out.Components = make(map[string]ComponentPhase, len(in.Components))
		for key, value := range in.Components {
			out.Components[key] = value
		}
	}
	if in.Conditions != nil {
		out.Conditions = append([]LabSessionCondition(nil), in.Conditions...)
	}
	return out
}
