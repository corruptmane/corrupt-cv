// Package s3 streams rendered PDFs out of object storage
// (OpenStack Swift s3api in compose, any S3-compatible store).
package s3

import (
	"context"
	"errors"
	"fmt"
	"io"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	awss3 "github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// Config holds the S3 connection settings.
type Config struct {
	Endpoint     string
	Region       string
	Bucket       string
	AccessKeyID  string
	SecretKey    string
	UsePathStyle bool
}

// ErrNotFound is returned when the object does not exist.
var ErrNotFound = errors.New("s3: object not found")

// Client fetches objects from the configured bucket.
type Client struct {
	s3     *awss3.Client
	bucket string
}

// New builds an S3 client with a static-credential, endpoint-override
// configuration (no ambient AWS config lookup).
func New(cfg Config) *Client {
	awsCfg := aws.Config{
		Region:      cfg.Region,
		Credentials: credentials.NewStaticCredentialsProvider(cfg.AccessKeyID, cfg.SecretKey, ""),
	}
	client := awss3.NewFromConfig(awsCfg, func(o *awss3.Options) {
		o.BaseEndpoint = aws.String(cfg.Endpoint)
		o.UsePathStyle = cfg.UsePathStyle
	})
	return &Client{s3: client, bucket: cfg.Bucket}
}

// Object is a streamed S3 object; the caller must Close the Body.
type Object struct {
	Body          io.ReadCloser
	ContentLength *int64
}

// Get streams an object from the bucket. Returns ErrNotFound when the
// key (or bucket) does not exist.
func (c *Client) Get(ctx context.Context, key string) (*Object, error) {
	out, err := c.s3.GetObject(ctx, &awss3.GetObjectInput{
		Bucket: aws.String(c.bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		var noKey *types.NoSuchKey
		var noBucket *types.NoSuchBucket
		if errors.As(err, &noKey) || errors.As(err, &noBucket) {
			return nil, ErrNotFound
		}
		return nil, fmt.Errorf("get s3 object %s: %w", key, err)
	}
	return &Object{
		Body:          out.Body,
		ContentLength: out.ContentLength,
	}, nil
}
