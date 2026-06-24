package tickets

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type Route struct {
	TenantID     string       `json:"tenantId"`
	AttemptID    string       `json:"attemptId"`
	SessionID    string       `json:"sessionId"`
	SessionEpoch int          `json:"sessionEpoch"`
	SessionRoute SessionRoute `json:"sessionRoute"`
	Permissions  []string     `json:"permissions"`
}

type SessionRoute struct {
	RouteRef string `json:"routeRef"`
	Endpoint string `json:"endpoint"`
	Protocol string `json:"protocol"`
}

type Client struct {
	APIURL       string
	ServiceToken string
	HTTP         *http.Client
}

func (c Client) Consume(ctx context.Context, ticket string) (Route, error) {
	body, _ := json.Marshal(map[string]string{"ticket": ticket})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.APIURL+"/internal/terminal/tickets/consume", bytes.NewReader(body))
	if err != nil {
		return Route{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-CLA-Service-Token", c.ServiceToken)
	client := c.HTTP
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return Route{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return Route{}, fmt.Errorf("ticket rejected: status %d", resp.StatusCode)
	}
	var route Route
	if err := json.NewDecoder(resp.Body).Decode(&route); err != nil {
		return Route{}, err
	}
	if route.SessionRoute.RouteRef == "" || route.SessionRoute.Endpoint == "" {
		return Route{}, fmt.Errorf("ticket route missing sessionRoute")
	}
	return route, nil
}
