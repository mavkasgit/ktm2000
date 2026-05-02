export type BackendIssue = {
  code?: string
  message?: string
  productCode?: string
  profileCode?: string
  pairedProductCode?: string
}

export type FlowIds = {
  importId?: string
  diffId?: string
  changeSetId?: string
  applyJobId?: string
  planId?: string
  approvalId?: string
  releaseBatchId?: string
  releaseJobId?: string
}
