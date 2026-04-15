.PHONY: generate-go

# Run from services/backend after installing:
#   protoc
#   protoc-gen-go
#   protoc-gen-go-grpc
# This generates backend/gen/llm/v1 so local `go build ./...` matches the
# import path used by the backend and the Docker build.
generate-go:
	protoc -I ../.. \
		--go_out=. --go_opt=module=backend \
		--go-grpc_out=. --go-grpc_opt=module=backend \
		proto/api/llm/v1/llm.proto