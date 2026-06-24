package tickets

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestConsumePostsTicketToControlPlane(t *testing.T) {
	var sawServiceToken bool
	var sawTicket bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/terminal/tickets/consume" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		sawServiceToken = r.Header.Get("X-CLA-Service-Token") == "svc-token"
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		sawTicket = body["ticket"] == "opaque-ticket"
		_ = json.NewEncoder(w).Encode(Route{
			TenantID:     "tenant_dev",
			AttemptID:    "a_123",
			SessionID:    "ls_123",
			SessionEpoch: 1,
			SessionRoute: SessionRoute{
				RouteRef: "route_123",
				Endpoint: "127.0.0.1:7777",
				Protocol: "tcp-sessionwire",
			},
			Permissions: []string{"terminal.connect", "terminal.resize"},
		})
	}))
	defer server.Close()

	route, err := Client{
		APIURL:       server.URL,
		ServiceToken: "svc-token",
		HTTP:         server.Client(),
	}.Consume(context.Background(), "opaque-ticket")
	if err != nil {
		t.Fatal(err)
	}
	if !sawServiceToken || !sawTicket {
		t.Fatalf("control plane request missing token or ticket")
	}
	if route.SessionRoute.RouteRef != "route_123" || route.SessionRoute.Endpoint != "127.0.0.1:7777" {
		t.Fatalf("unexpected route %#v", route)
	}
}

func TestConsumeRejectsMissingSessionRoute(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"tenantId":     "tenant_dev",
			"attemptId":    "a_123",
			"sessionId":    "ls_123",
			"sessionEpoch": 1,
			"permissions":  []string{"terminal.connect"},
		})
	}))
	defer server.Close()

	_, err := Client{APIURL: server.URL, ServiceToken: "svc-token", HTTP: server.Client()}.
		Consume(context.Background(), "bad-route")
	if err == nil {
		t.Fatal("expected missing route error")
	}
}

func TestConsumeRejectsNonOK(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "no", http.StatusUnauthorized)
	}))
	defer server.Close()

	_, err := Client{APIURL: server.URL, ServiceToken: "svc-token", HTTP: server.Client()}.
		Consume(context.Background(), "bad-ticket")
	if err == nil {
		t.Fatal("expected rejection error")
	}
}
