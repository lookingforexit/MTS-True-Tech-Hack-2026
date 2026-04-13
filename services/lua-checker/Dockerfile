FROM golang:1.26-alpine AS builder

RUN apk add --no-cache git ca-certificates protobuf-dev protoc

WORKDIR /app

COPY services/lua-checker/go.mod services/lua-checker/go.sum ./
RUN go mod download && go mod verify

RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && \
    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

COPY proto ./proto
COPY services/lua-checker .

RUN protoc -I . \
    --go_out=. --go_opt=module=lua-checker \
    --go-grpc_out=. --go-grpc_opt=module=lua-checker \
    proto/api/lua_checker/v1/checker.proto

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /lua-checker ./cmd/server/main.go

FROM alpine:3.21

RUN apk add --no-cache ca-certificates

WORKDIR /root/

COPY --from=builder /lua-checker .

EXPOSE 50053

CMD ["./lua-checker"]
