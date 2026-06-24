package v1

import "testing"

func TestWorkspaceTypesAreReservedButStable(t *testing.T) {
	if WorkspaceTerminal != "TERMINAL" {
		t.Fatalf("terminal workspace changed: %q", WorkspaceTerminal)
	}
	if WorkspaceRemoteDesktop != "REMOTE_DESKTOP" {
		t.Fatalf("remote desktop workspace changed: %q", WorkspaceRemoteDesktop)
	}
	if WorkspaceSimulated != "SIMULATED" {
		t.Fatalf("simulated workspace changed: %q", WorkspaceSimulated)
	}
}

func TestLabSessionSpecCarriesOpaqueRouteRef(t *testing.T) {
	spec := LabSessionSpec{
		TenantID:         "tenant_dev",
		AttemptID:        "a_123",
		Epoch:            1,
		WorkspaceType:    WorkspaceTerminal,
		RuntimeClassName: "gvisor",
		TTLSeconds:       5400,
		RouteRef:         "route_123",
	}
	if spec.RouteRef == "" || spec.WorkspaceType != WorkspaceTerminal {
		t.Fatalf("bad spec %#v", spec)
	}
}

func TestLabSessionStatusCarriesNamespaceComponentsAndConditions(t *testing.T) {
	status := LabSessionStatus{
		Phase:              string(SessionReady),
		ObservedGeneration: 4,
		NamespaceName:      "lab-a-123-e1",
		RouteReady:         true,
		Components: map[string]ComponentPhase{
			"workspace":   ComponentReady,
			"target":      ComponentReady,
			"oracleProbe": ComponentReady,
		},
		ExpiresAt: "2026-06-24T10:15:00Z",
		Conditions: []LabSessionCondition{
			{Type: "ResourcesCreated", Status: "True", Reason: "Reconciled"},
		},
	}
	if status.NamespaceName == "" || status.Components["workspace"] != ComponentReady {
		t.Fatalf("status lost session namespace or component readiness: %#v", status)
	}
	if status.ObservedGeneration != 4 {
		t.Fatalf("status lost observed generation: %#v", status)
	}
	if status.Components["workspace"] == ComponentFailed {
		t.Fatalf("component phase constants overlap")
	}
	if SessionPending == SessionReady || SessionTerminating == SessionReady {
		t.Fatalf("session phase constants overlap")
	}
}
