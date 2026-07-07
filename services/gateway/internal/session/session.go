// Package session implements the HMAC-signed anonymous visitor cookie.
//
// The cookie "cv_visitor" carries "uuid.hexsig" where hexsig is
// HMAC-SHA256(uuid, secret) hex-encoded. It is auto-issued on first
// visit; every profile and job is scoped to the visitor id.
package session

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// CookieName is the visitor cookie name.
const CookieName = "cv_visitor"

const contextKey = "session.visitor_id"

const cookieMaxAge = 365 * 24 * 60 * 60 // one year

// Sign returns the signed cookie value for a visitor id.
func Sign(visitorID string, secret []byte) string {
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(visitorID))
	return visitorID + "." + hex.EncodeToString(mac.Sum(nil))
}

// Verify parses a signed cookie value and returns the visitor id.
// It returns false when the value is malformed or the signature does
// not match.
func Verify(value string, secret []byte) (string, bool) {
	id, sigHex, ok := strings.Cut(value, ".")
	if !ok || id == "" {
		return "", false
	}
	if _, err := uuid.Parse(id); err != nil {
		return "", false
	}
	sig, err := hex.DecodeString(sigHex)
	if err != nil {
		return "", false
	}
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(id))
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return "", false
	}
	return id, true
}

// Middleware validates the visitor cookie, issuing a fresh one when it
// is missing or invalid, and stores the visitor id on the gin context.
func Middleware(secret []byte) gin.HandlerFunc {
	return func(c *gin.Context) {
		var visitorID string
		if value, err := c.Cookie(CookieName); err == nil {
			if id, ok := Verify(value, secret); ok {
				visitorID = id
			}
		}
		if visitorID == "" {
			visitorID = uuid.NewString()
			c.SetSameSite(http.SameSiteLaxMode)
			c.SetCookie(CookieName, Sign(visitorID, secret), cookieMaxAge, "/", "", false, true)
		}
		c.Set(contextKey, visitorID)
		c.Next()
	}
}

// VisitorID returns the visitor id stored by Middleware.
func VisitorID(c *gin.Context) string {
	return c.GetString(contextKey)
}
