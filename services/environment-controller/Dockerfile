FROM golang:1.22-bookworm AS build
WORKDIR /src
ENV GOWORK=off
COPY services/environment-controller/go.mod services/environment-controller/go.sum services/environment-controller/
RUN cd services/environment-controller && go mod download
COPY services/environment-controller services/environment-controller
RUN cd services/environment-controller && CGO_ENABLED=0 go build -o /out/environment-controller ./cmd/controller

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/environment-controller /environment-controller
USER nonroot:nonroot
ENTRYPOINT ["/environment-controller"]
