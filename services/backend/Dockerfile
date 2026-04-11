FROM golang:1.26-alpine AS builder

RUN apk add --no-cache git ca-certificates protobuf-dev protoc

WORKDIR /app

COPY services/backend/go.mod services/backend/go.sum ./
RUN go mod download && go mod verify

RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && \
    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

COPY proto ./proto
COPY services/backend .

RUN protoc -I . \
    --go_out=. --go_opt=module=backend \
    --go-grpc_out=. --go-grpc_opt=module=backend \
    proto/api/llm/v1/llm.proto

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /backend-server ./cmd/server/main.go

FROM alpine:3.21

RUN apk add --no-cache ca-certificates

WORKDIR /root/

COPY --from=builder /backend-server .

EXPOSE 8080

CMD ["./backend-server"]
