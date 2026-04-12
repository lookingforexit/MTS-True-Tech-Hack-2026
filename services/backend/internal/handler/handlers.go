package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	llmv1 "backend/gen/llm/v1"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type GenerateRequest struct {
	Prompt              string          `json:"prompt"`
	SessionID           string          `json:"session_id,omitempty"`
	ClarificationAnswer string          `json:"clarification_answer,omitempty"`
	Context             json.RawMessage `json:"context,omitempty"`
}

type GenerateResponse struct {
	Code      string `json:"code,omitempty"`
	Question  string `json:"question,omitempty"`
	SessionID string `json:"session_id,omitempty"`
	Error     string `json:"error,omitempty"`
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
			out.Question = resp.GetClarificationQuestion()
		case llmv1.SessionPhase_DONE, llmv1.SessionPhase_CODE_GENERATED:
			out.Code = resp.GetCode()
		case llmv1.SessionPhase_ERROR:
			out.Error = resp.GetError()
		default:
			if resp.GetCode() != "" {
				out.Code = resp.GetCode()
			} else if resp.GetClarificationQuestion() != "" {
				out.Question = resp.GetClarificationQuestion()
			}
		}

		ctx.JSON(http.StatusOK, out)
	}
}
