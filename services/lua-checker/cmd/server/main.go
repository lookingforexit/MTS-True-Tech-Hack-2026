package main

import (
	"fmt"
	"net"
	"os"
	"os/signal"
	"syscall"

	"lua-checker/internal/config"
	"lua-checker/internal/handler"

	"google.golang.org/grpc"

	checker "lua-checker/gen/lua_checker/v1"
)

func main() {
	cfg := config.LoadConfig()

	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", cfg.Port))
	if err != nil {
		fmt.Printf("❌ Failed to listen: %v\n", err)
		os.Exit(1)
	}

	grpcServer := grpc.NewServer()
	server := handler.NewServer()
	checker.RegisterLuaCheckerServer(grpcServer, server)

	fmt.Printf("🚀 Lua Checker gRPC server started on port %s\n", cfg.Port)

	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		fmt.Println("\n🛑 Shutting down...")
		grpcServer.GracefulStop()
	}()

	if err := grpcServer.Serve(lis); err != nil {
		fmt.Printf("❌ Failed to serve: %v\n", err)
		os.Exit(1)
	}
}
