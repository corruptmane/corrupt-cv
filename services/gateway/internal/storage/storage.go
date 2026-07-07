// Package storage reads rendered PDFs from an S3-compatible backend using
// aws-sdk-go-v2 (service/s3 only). A BaseEndpoint override + path-style
// addressing makes the same client work against LocalStack and real AWS S3.
package storage

import (
	"context"
	"io"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws"
)

type Config struct {
	Endpoint     string
	Region       string
	Bucket       string
	AccessKey    string
	SecretKey    string
	UsePathStyle bool
}

type Store struct {
	client *s3.Client
	bucket string
}

func New(cfg Config) *Store {
	opts := s3.Options{
		Region:       cfg.Region,
		BaseEndpoint: aws.String(cfg.Endpoint),
		UsePathStyle: cfg.UsePathStyle,
		Credentials:  credentials.NewStaticCredentialsProvider(cfg.AccessKey, cfg.SecretKey, ""),
	}
	otelaws.AppendMiddlewares(&opts.APIOptions) // OTel spans per S3 call
	return &Store{client: s3.New(opts), bucket: cfg.Bucket}
}

// Get returns the object body (caller must Close) and its size.
func (s *Store) Get(ctx context.Context, key string) (io.ReadCloser, int64, error) {
	out, err := s.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(s.bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return nil, 0, err
	}
	var size int64
	if out.ContentLength != nil {
		size = *out.ContentLength
	}
	return out.Body, size, nil
}
