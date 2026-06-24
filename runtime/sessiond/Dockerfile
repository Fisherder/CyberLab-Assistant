FROM golang:1.22-bookworm AS build
WORKDIR /src
ENV GOWORK=off
COPY go.work ./
COPY packages/sessionwire/go.mod packages/sessionwire/go.mod
COPY runtime/sessiond/go.mod runtime/sessiond/go.sum runtime/sessiond/
RUN cd runtime/sessiond && go mod download
COPY packages/sessionwire packages/sessionwire
COPY runtime/sessiond runtime/sessiond
RUN cd runtime/sessiond && CGO_ENABLED=0 go build -o /out/cla-sessiond ./cmd/sessiond

FROM debian:bookworm-slim
RUN useradd -m -u 10001 student && apt-get update && apt-get install -y --no-install-recommends bash && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/cla-sessiond /usr/local/bin/cla-sessiond
USER student
WORKDIR /workspace
EXPOSE 7777
ENTRYPOINT ["/usr/local/bin/cla-sessiond"]
