package handler

import (
	"context"

	checker "lua-checker/gen/lua_checker/v1"
	"lua-checker/internal/service"
)

type Server struct {
	checker.UnimplementedLuaCheckerServer
}

func NewServer() *Server {
	return &Server{}
}

func (s *Server) Check(ctx context.Context, req *checker.CheckRequest) (*checker.CheckResponse, error) {
	luaChecker := &service.LuaChecker{}
	luaChecker.Validate(req.GetScript())
	violations := append([]string(nil), luaChecker.Errors...)

	return &checker.CheckResponse{
		Valid:      len(violations) == 0,
		Violations: violations,
	}, nil
}
