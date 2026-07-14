process.stdout.write(
    JSON.stringify({
        GITHUB_TOKEN: Object.hasOwn(process.env, "GITHUB_TOKEN"),
        COPILOT_GITHUB_TOKEN: Object.hasOwn(process.env, "COPILOT_GITHUB_TOKEN"),
        GH_TOKEN: Object.hasOwn(process.env, "GH_TOKEN"),
    }),
);
