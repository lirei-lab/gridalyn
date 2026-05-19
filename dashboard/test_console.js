import puppeteer from 'puppeteer';

(async () => {
    const browser = await puppeteer.launch({
      headless: "new",
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-web-security']
    });
    const page = await browser.newPage();

    page.on('console', async msg => {
        try {
            const args = await Promise.all(msg.args().map(a => a.jsonValue()));
            console.log(`PAGE LOG [${msg.type()}]:`, JSON.stringify(args).substring(0, 100));
        } catch {
            console.log(`PAGE LOG [${msg.type()}]:`, msg.text());
        }
    });

    try {
        await page.goto('http://localhost:5173/', { waitUntil: 'networkidle0', timeout: 10000 });
        console.log("Navigation complete.");
    } catch (err) {
        console.log("Navigation timeout or error:", err.message);
    }

    await new Promise(r => setTimeout(r, 2000));
    await browser.close();
})();
