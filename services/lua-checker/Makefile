.PHONY: generate-go
generate-go:
	protoc -I ../.. \
		--go_out=. --go_opt=module=lua-checker \
		--go-grpc_out=. --go-grpc_opt=module=lua-checker \
		proto/api/lua_checker/v1/checker.proto
