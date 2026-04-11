.PHONY: generate-go
generate-go:
	protoc -I ../.. \
		--go_out=. --go_opt=module=backend \
		--go-grpc_out=. --go-grpc_opt=module=backend \
		proto/api/llm/v1/llm.proto
