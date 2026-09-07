/**
 * Runtime configuration for the MoodJournal frontend.
 *
 * This is the ONLY file that knows the API address. It is rewritten by
 * scripts/deploy_frontend.ps1 during deployment, using the ApiEndpoint output
 * of the CloudFormation stack, so no HTML or JS file needs editing by hand.
 *
 * The value below is the local development default. The deployed copy in S3
 * contains the API Gateway URL instead.
 */
window.MOODJOURNAL_CONFIG = {
  API_BASE_URL: "http://127.0.0.1:8000",
};
