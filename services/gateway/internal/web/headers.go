package web

import "github.com/gin-gonic/gin"

// Security header values applied to every app-server response, before
// the first write so streaming endpoints (SSE) keep them.
const (
	headerContentTypeOptions = "X-Content-Type-Options"
	valueNosniff             = "nosniff"

	headerReferrerPolicy = "Referrer-Policy"
	valueReferrerPolicy  = "strict-origin-when-cross-origin"

	headerCSP = "Content-Security-Policy"
	valueCSP  = "default-src 'self'"

	headerHSTS = "Strict-Transport-Security"
	valueHSTS  = "max-age=31536000; includeSubDomains"
)

// securityHeaders sets the baseline response headers on every request.
// HSTS is only sent when cookies are Secure: advertising HTTPS-only
// from a plaintext deployment would break plain-HTTP visitors.
func (s *Server) securityHeaders(secureCookies bool) gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.Writer.Header()
		h.Set(headerContentTypeOptions, valueNosniff)
		h.Set(headerReferrerPolicy, valueReferrerPolicy)
		h.Set(headerCSP, valueCSP)
		if secureCookies {
			h.Set(headerHSTS, valueHSTS)
		}
		c.Next()
	}
}
