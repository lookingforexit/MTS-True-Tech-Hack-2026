package handler

import (
	"backend/internal/client"
	"github.com/gin-gonic/gin"
	"net/http"
)

type PostRequest struct {
	prompt string
}

type PostResponse struct {
	code string
}

func Handler(agent client.AgentClient) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		var req PostRequest
		if err := ctx.ShouldBindJSON(&req); err != nil {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		code := "Ivanou"

		ctx.JSON(http.StatusOK, PostResponse{
			code: code,
		})
	}
}
