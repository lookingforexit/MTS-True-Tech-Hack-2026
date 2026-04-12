package main

import (
	"fmt"
	"log"

	llmv1 "backend/gen/llm/v1"
	"backend/internal/config"
	"backend/internal/handler"

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

	defer conn.Close()

	llmClient := llmv1.NewLLMServiceClient(conn)

	router := gin.Default()
	router.GET("/health", handler.HealthHandler())
	router.POST("/generate", handler.Handler(llmClient))

	addr := fmt.Sprintf(":%s", cfg.Port)
	log.Printf("listening on %s, LLM at %s", addr, cfg.LLMAddr)
	if err := router.Run(addr); err != nil {
		log.Fatal(err)
	}
}
