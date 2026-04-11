FROM golang:1.26-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download && go mod verify

COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /backend-server ./cmd/server/main.go

FROM alpine:3.21

RUN apk add --no-cache ca-certificates

WORKDIR /root/

COPY --from=builder /backend-server .

EXPOSE 8080

CMD ["./backend-server"]
