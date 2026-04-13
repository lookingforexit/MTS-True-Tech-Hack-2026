.PHONY: generate-go

# Run from services/lua-checker after installing:
#   protoc
#   protoc-gen-go
#   protoc-gen-go-grpc
# This reads the shared proto tree and writes only to services/lua-checker/gen.
generate-go:
	protoc -I ../.. \
		--go_out=. --go_opt=module=lua-checker \
		--go-grpc_out=. --go-grpc_opt=module=lua-checker \
		proto/api/lua_checker/v1/checker.proto
