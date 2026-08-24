package session

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

func TestSignVerifyRoundTrip(t *testing.T) {
	secret := []byte("test-secret")
	id := uuid.NewString()

	value := Sign(id, secret)
	got, ok := Verify(value, secret)
	if !ok {
		t.Fatalf("Verify(%q) failed, want success", value)
	}
	if got != id {
		t.Fatalf("Verify returned %q, want %q", got, id)
	}
}

func TestVerifyRejectsTamperedID(t *testing.T) {
	secret := []byte("test-secret")
	value := Sign(uuid.NewString(), secret)

	other := uuid.NewString()
	_, sig, _ := strings.Cut(value, ".")
	if _, ok := Verify(other+"."+sig, secret); ok {
		t.Fatal("Verify accepted a value with a swapped visitor id")
	}
}

func TestVerifyRejectsTamperedSignature(t *testing.T) {
	secret := []byte("test-secret")
	id := uuid.NewString()
	value := Sign(id, secret)

	// Flip a hex digit in the signature.
	last := value[len(value)-1]
	repl := byte('0')
	if last == '0' {
		repl = '1'
	}
	tampered := value[:len(value)-1] + string(repl)
	if _, ok := Verify(tampered, secret); ok {
		t.Fatal("Verify accepted a value with a tampered signature")
	}
}

func TestVerifyRejectsWrongSecret(t *testing.T) {
	value := Sign(uuid.NewString(), []byte("secret-a"))
	if _, ok := Verify(value, []byte("secret-b")); ok {
		t.Fatal("Verify accepted a value signed with a different secret")
	}
}

func TestVerifyRejectsMalformed(t *testing.T) {
	secret := []byte("test-secret")
	for _, value := range []string{
		"",
		"no-dot-at-all",
		".deadbeef",
		uuid.NewString(),               // no signature
		"not-a-uuid.deadbeef",          // invalid uuid
		uuid.NewString() + ".zzzz",     // invalid hex
		uuid.NewString() + ".deadbeef", // wrong signature
	} {
		if _, ok := Verify(value, secret); ok {
			t.Errorf("Verify(%q) succeeded, want rejection", value)
		}
	}
}

func TestMiddlewareCookieAttributes(t *testing.T) {
	cases := []struct {
		name       string
		secure     bool
		wantSecure bool
	}{
		{"insecure", false, false},
		{"secure", true, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			r := gin.New()
			r.GET("/", Middleware([]byte("test-secret"), tc.secure), func(c *gin.Context) {
				c.Status(200)
			})
			rec := httptest.NewRecorder()
			r.ServeHTTP(rec, httptest.NewRequest("GET", "/", nil))

			var cookie *http.Cookie
			for _, c := range rec.Result().Cookies() {
				if c.Name == CookieName {
					cookie = c
					break
				}
			}
			if cookie == nil {
				t.Fatal("no cv_visitor cookie issued")
			}
			if cookie.Secure != tc.wantSecure {
				t.Fatalf("cookie Secure = %v, want %v", cookie.Secure, tc.wantSecure)
			}
			if !cookie.HttpOnly {
				t.Error("cookie must remain HttpOnly")
			}
			if _, ok := Verify(cookie.Value, []byte("test-secret")); !ok {
				t.Errorf("issued cookie %q does not verify", cookie.Value)
			}
		})
	}
}
