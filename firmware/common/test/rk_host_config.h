/* Minimal mbedTLS 3.x configuration for the host vector test: AES-GCM, SHA-256, HKDF only. */
#ifndef RK_HOST_CONFIG_H
#define RK_HOST_CONFIG_H

#define MBEDTLS_PLATFORM_C
#define MBEDTLS_AES_C
#define MBEDTLS_CIPHER_C
#define MBEDTLS_GCM_C
#define MBEDTLS_MD_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_HKDF_C
#define MBEDTLS_NO_PLATFORM_ENTROPY

#endif
