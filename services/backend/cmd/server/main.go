package main

import (
	llmv1 "backend/gen/llm/v1"
	"backend/internal/config"
	"backend/internal/handler"
	"backend/internal/session"
	"fmt"
	"log"
	"time"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	cfg := config.LoadConfig()

	conn, err := grpc.NewClient(cfg.LLMAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("grpc dial %s: %v", cfg.LLMAddr, err)
	}

	defer func(conn *grpc.ClientConn) {
		err := conn.Close()
		if err != nil {
			fmt.Printf("grpc dial %s: %v", cfg.LLMAddr, err)
		}
	}(conn)

	stateStore := session.NewStore(cfg.RedisAddr, 1020*time.Second)

	llmClient := llmv1.NewLLMServiceClient(conn)

	router := gin.Default()
	router.GET("/health", handler.HealthHandler(stateStore))
	router.POST("/generate", handler.Handler(llmClient, stateStore))

	addr := fmt.Sprintf(":%s", cfg.Port)
	log.Printf("listening on %s, LLM at %s", addr, cfg.LLMAddr)
	if err := router.Run(addr); err != nil {
		log.Fatal(err)
	}
}
