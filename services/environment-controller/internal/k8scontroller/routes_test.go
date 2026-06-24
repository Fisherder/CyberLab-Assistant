package k8scontroller

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"cla-platform/services/environment-controller/internal/labcontroller"
)

func TestControlPlaneRouteRegistryRegistersAndUnregistersRoute(t *testing.T) {
	var requests []string
	var bodies []map[string]any
	var serviceTokens []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.URL.Path)
		serviceTokens = append(serviceTokens, r.Header.Get("X-CLA-Service-Token"))
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		bodies = append(bodies, body)
		w.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	registry := ControlPlaneRouteRegistry{
		APIURL:       server.URL + "/",
		ServiceToken: "svc-token",
		HTTP:         server.Client(),
	}
	err := registry.RegisterRoute(context.Background(), "a_123", 2, labcontroller.RouteRegistration{
		RouteRef:    "route_123",
		Namespace:   "lab-a-123-e2",
		ServiceName: labcontroller.WorkspaceServiceName,
		Port:        labcontroller.SessiondPort,
	})
	if err != nil {
		t.Fatalf("register route: %v", err)
	}
	err = registry.UnregisterRoute(context.Background(), "a_123", 2, "route_123")
	if err != nil {
		t.Fatalf("unregister route: %v", err)
	}
	err = registry.RevokeTickets(context.Background(), "a_123", 2, "route_123")
	if err != nil {
		t.Fatalf("revoke tickets: %v", err)
	}

	expectedRegisterPath := "/internal/attempts/a_123/sessions/2/route"
	expectedUnregisterPath := "/internal/attempts/a_123/sessions/2/route/unregister"
	expectedRevokePath := "/internal/attempts/a_123/sessions/2/tickets/revoke"
	if requests[0] != expectedRegisterPath || requests[1] != expectedUnregisterPath || requests[2] != expectedRevokePath {
		t.Fatalf("requests = %#v", requests)
	}
	if serviceTokens[0] != "svc-token" || serviceTokens[1] != "svc-token" || serviceTokens[2] != "svc-token" {
		t.Fatalf("service tokens = %#v", serviceTokens)
	}
	if bodies[0]["routeRef"] != "route_123" {
		t.Fatalf("register body = %#v", bodies[0])
	}
	if bodies[0]["endpoint"] != "workspace-sessiond.lab-a-123-e2.svc.cluster.local:7777" {
		t.Fatalf("register endpoint = %#v", bodies[0])
	}
	if bodies[0]["protocol"] != "tcp-sessionwire" {
		t.Fatalf("register protocol = %#v", bodies[0])
	}
	if bodies[1]["routeRef"] != "route_123" {
		t.Fatalf("unregister body = %#v", bodies[1])
	}
	if bodies[2]["routeRef"] != "route_123" {
		t.Fatalf("revoke body = %#v", bodies[2])
	}
}

func TestControlPlaneRouteRegistryRejectsNonSuccessStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusConflict)
	}))
	defer server.Close()

	err := (ControlPlaneRouteRegistry{
		APIURL:       server.URL,
		ServiceToken: "svc-token",
		HTTP:         server.Client(),
	}).RegisterRoute(context.Background(), "a_123", 2, labcontroller.RouteRegistration{
		RouteRef:    "route_123",
		Namespace:   "lab-a-123-e2",
		ServiceName: labcontroller.WorkspaceServiceName,
		Port:        labcontroller.SessiondPort,
	})
	if err == nil {
		t.Fatalf("expected non-success status to return an error")
	}
}
