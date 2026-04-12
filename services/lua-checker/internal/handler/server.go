package handler

import (
	"context"

	checker "lua-checker/gen/lua_checker/v1"
	"lua-checker/internal/service"
)

type Server struct {
	checker.UnimplementedLuaCheckerServer
	checker *service.LuaChecker
}

func NewServer() *Server {
	return &Server{
		checker: &service.LuaChecker{},
	}
}

func (s *Server) Check(ctx context.Context, req *checker.CheckRequest) (*checker.CheckResponse, error) {
	s.checker.Validate(req.GetScript())

	return &checker.CheckResponse{
		Valid:      len(s.checker.Errors) == 0,
		Violations: s.checker.Errors,
	}, nil
}
