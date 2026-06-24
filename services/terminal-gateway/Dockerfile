FROM golang:1.22-bookworm AS build
WORKDIR /src
ENV GOWORK=off
COPY go.work ./
COPY packages/sessionwire/go.mod packages/sessionwire/go.mod
COPY services/terminal-gateway/go.mod services/terminal-gateway/go.sum services/terminal-gateway/
RUN cd services/terminal-gateway && go mod download
COPY packages/sessionwire packages/sessionwire
COPY services/terminal-gateway services/terminal-gateway
RUN cd services/terminal-gateway && CGO_ENABLED=0 go build -o /out/terminal-gateway ./cmd/gateway

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/terminal-gateway /terminal-gateway
USER nonroot:nonroot
EXPOSE 8081
ENTRYPOINT ["/terminal-gateway"]
