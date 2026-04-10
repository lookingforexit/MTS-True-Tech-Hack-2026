package main

import (
	"backend/internal/config"
	"fmt"

	"github.com/gin-gonic/gin"
)

func main() {
	cfg := config.LoadConfig()

	router := gin.Default()

	router.POST("/generate")

	router.Run(fmt.Sprintf(":%s", cfg.Port))
}
