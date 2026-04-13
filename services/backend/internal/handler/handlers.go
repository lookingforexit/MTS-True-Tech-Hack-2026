package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	llmv1 "backend/gen/llm/v1"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// HealthHandler returns a simple health check response.
func HealthHandler() gin.HandlerFunc {
	return func(ctx *gin.Context) {
		ctx.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}

type GenerateRequest struct {
	Prompt              string          `json:"prompt"`
	SessionID           string          `json:"session_id,omitempty"`
	ClarificationAnswer string          `json:"clarification_answer,omitempty"`
	Context             json.RawMessage `json:"context,omitempty"`
}

type GenerateResponse struct {
	Code             string `json:"code,omitempty"`
	Question         string `json:"question,omitempty"`
	SessionID        string `json:"session_id,omitempty"`
	Error            string `json:"error,omitempty"`
	RepairCount      int32  `json:"repair_count,omitempty"`
	ValidationOutput string `json:"validation_output,omitempty"`
	ValidationError  string `json:"validation_error,omitempty"`
}

func wrapLuaTransport(raw string) string {
	if raw == "" {
		return ""
	}
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "lua{") && strings.HasSuffix(trimmed, "}lua") {
		return raw
	}
	return fmt.Sprintf("lua{%s}lua", raw)
}

func wrapTextTransport(raw string) string {
	if raw == "" {
		return ""
	}
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "text{") && strings.HasSuffix(trimmed, "}text") {
		return raw
	}
	return fmt.Sprintf("text{%s}text", raw)
}

func Handler(client llmv1.LLMServiceClient) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		var req GenerateRequest
		if err := ctx.ShouldBindJSON(&req); err != nil {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		if req.ClarificationAnswer != "" && req.SessionID == "" {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": "session_id is required with clarification_answer"})
			return
		}
		if req.ClarificationAnswer == "" && req.Prompt == "" {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": "prompt is required unless sending clarification_answer"})
			return
		}

		if len(req.Context) > 0 {
			var parsed map[string]interface{}
			if err := json.Unmarshal(req.Context, &parsed); err != nil {
				ctx.JSON(http.StatusBadRequest, gin.H{"error": "context must be valid JSON object: " + err.Error()})
				return
			}
		}

		rpcCtx, cancel := context.WithTimeout(ctx.Request.Context(), 900*time.Second)
		defer cancel()

		var resp *llmv1.SessionResponse
		var err error

		if req.ClarificationAnswer != "" {
			resp, err = client.AnswerClarification(rpcCtx, &llmv1.AnswerRequest{
				SessionId: req.SessionID,
				Answer:    req.ClarificationAnswer,
			})
		} else {
			sr := &llmv1.SessionRequest{Request: req.Prompt}
			if req.SessionID != "" {
				sr.SessionId = req.SessionID
			}
			if len(req.Context) > 0 {
				sr.Context = string(req.Context)
			}
			resp, err = client.StartOrContinue(rpcCtx, sr)
		}

		if err != nil {
			st, _ := status.FromError(err)
			code := http.StatusBadGateway
			if st.Code() == codes.NotFound {
				code = http.StatusNotFound
			} else if st.Code() == codes.FailedPrecondition {
				code = http.StatusConflict
			}
			ctx.JSON(code, GenerateResponse{Error: err.Error()})
			return
		}

		out := GenerateResponse{SessionID: resp.GetSessionId()}

		switch resp.GetPhase() {
		case llmv1.SessionPhase_CLARIFICATION_NEEDED:
			out.Question = wrapTextTransport(resp.GetClarificationQuestion())
		case llmv1.SessionPhase_DONE, llmv1.SessionPhase_CODE_GENERATED:
			out.Code = wrapLuaTransport(resp.GetCode())
		case llmv1.SessionPhase_ERROR:
			out.Error = resp.GetError()
			out.ValidationError = resp.GetValidationError()
			out.ValidationOutput = resp.GetValidationOutput()
			out.RepairCount = resp.GetRepairCount()
		default:
			if resp.GetCode() != "" {
				out.Code = wrapLuaTransport(resp.GetCode())
			} else if resp.GetClarificationQuestion() != "" {
				out.Question = wrapTextTransport(resp.GetClarificationQuestion())
			} else if resp.GetError() != "" {
				out.Error = resp.GetError()
				out.ValidationError = resp.GetValidationError()
				out.ValidationOutput = resp.GetValidationOutput()
				out.RepairCount = resp.GetRepairCount()
			}
		}

		if out.Error != "" && out.Code == "" && out.Question == "" {
			ctx.JSON(http.StatusUnprocessableEntity, out)
			return
		}

		ctx.JSON(http.StatusOK, out)
	}
}
