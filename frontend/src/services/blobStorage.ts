/**
 * Azure Blob Storage — direct upload from the browser.
 *
 * Uses @azure/storage-blob SDK with a container-level SAS token
 * fetched from the backend so the frontend can PUT blobs directly.
 */

import {
  BlobServiceClient,
  ContainerClient,
  type BlockBlobUploadOptions,
} from '@azure/storage-blob';
import type { SasTokenResponse } from '../types/licitacion';

function getContainerClient(auth: SasTokenResponse): ContainerClient {
  const blobServiceUrl = `https://${auth.account}.blob.core.windows.net?${auth.sas_token}`;
  const blobServiceClient = new BlobServiceClient(blobServiceUrl);
  return blobServiceClient.getContainerClient(auth.container);
}

// ── Public API ──────────────────────────────────────────────────────────────────

export interface BlobUploadResult {
  blob_url: string;
  filename: string;
  size_bytes: number;
}

/**
 * Uploads a single file to Azure Blob Storage.
 *
 * @param file       - File to upload
 * @param prefix     - Path prefix (typically the licitacion UUID)
 * @param auth       - SAS token details fetched from backend
 * @param onProgress - Optional callback with progress percentage (0–100)
 */
export async function uploadFileToBlob(
  file: File,
  prefix: string,
  auth: SasTokenResponse,
  onProgress?: (pct: number) => void,
): Promise<BlobUploadResult> {
  const containerClient = getContainerClient(auth);

  // Build blob path: <prefix>/<safe_filename>
  const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
  const blobPath = `${prefix}/${safeName}`;
  const blockBlobClient = containerClient.getBlockBlobClient(blobPath);

  const options: BlockBlobUploadOptions = {
    blobHTTPHeaders: {
      blobContentType: file.type || 'application/pdf',
    },
    onProgress: (ev) => {
      if (onProgress && ev.loadedBytes !== undefined) {
        const pct = Math.round((ev.loadedBytes / file.size) * 100);
        onProgress(Math.min(pct, 100));
      }
    },
  };

  await blockBlobClient.uploadData(file, options);

  return {
    blob_url: blockBlobClient.url.split('?')[0], // strip SAS token from URL
    filename: file.name,
    size_bytes: file.size,
  };
}

/**
 * Uploads multiple files to blob storage with individual progress tracking.
 *
 * @param files      - Array of files with their document type labels
 * @param prefix     - Path prefix (licitacion UUID)
 * @param auth       - SAS token details fetched from backend
 * @param onProgress - Called for each file with (fileIndex, pct)
 */
export async function uploadFilesToBlob(
  files: { file: File; label: string }[],
  prefix: string,
  auth: SasTokenResponse,
  onProgress?: (fileIndex: number, pct: number) => void,
): Promise<BlobUploadResult[]> {
  const results: BlobUploadResult[] = [];

  for (let i = 0; i < files.length; i++) {
    const result = await uploadFileToBlob(
      files[i].file,
      prefix,
      auth,
      (pct) => onProgress?.(i, pct),
    );
    results.push(result);
  }

  return results;
}
