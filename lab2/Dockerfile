FROM golang:1.19 AS builder
COPY go.mod go.sum main.go /src/
WORKDIR /src
RUN go build .
FROM ubuntu:jammy
RUN apt-get update && apt-get install -y iputils-ping
COPY --from=builder /src/mtu-check /usr/local/bin/mtu-check
ENTRYPOINT [ "/usr/local/bin/mtu-check" ]
