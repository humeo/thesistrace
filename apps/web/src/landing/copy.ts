export type Language = 'en' | 'zh';
export const copy = {
    en: {
        brand: 'QuantTrace', descriptor: 'Quantitative Research Workbench', home: 'QuantTrace home', navigation: 'Main navigation', method: 'How it works', preview: 'Product preview', login: 'Log in',
        headline: ['Put every hypothesis ', 'to the test.'], subtitle: 'From factor research and strategy backtesting to daily tracking.', explore: 'Explore QuantTrace', stepsLabel: 'Three research steps', viewExample: 'View example', demo: 'Demo content',
        previewTitle: 'An experiment in short-term reversal.', previewIntro: 'Follow one question through the research process.', previewNote: 'An interactive demo. No live research tasks are run.', stagesLabel: 'Research stages', alpha: 'Alpha expression',
        stages: [
            { title: 'Form a hypothesis', description: 'Turn an investment idea into a testable question.', label: 'Research hypothesis', detail: 'Do stocks that recently fell tend to reverse in the short term?', action: 'Explore validation', body: 'Express your intuition as a formula, then check whether the research supports it.' },
            { title: 'Test the evidence', description: 'Evaluate your hypothesis with backtests and analysis.', label: 'Validation approach', detail: 'Examine factor performance, strategy returns and drawdowns over a historical period.', action: 'Explore daily tracking', body: 'Look beyond returns: assess stability and understand which research settings your conclusions depend on.' },
            { title: 'Keep observing', description: 'Track daily results and observe long-term stability.', label: 'Ongoing observation', detail: 'Start daily tracking from a research result and observe performance in subsequent trading sessions.', action: 'Revisit the hypothesis', body: 'A historical backtest gives you a starting point. Continued observation adds evidence.' },
        ],
        validation: [['Factor performance', 'Examine the relationship between signals and subsequent returns'], ['Strategy backtest', 'Inspect returns, drawdowns and changes in holdings'], ['Research context', 'Keep the expression, parameters and data context together']],
        tracking: [['Starting point', 'An existing research result'], ['Frequency', 'After the market closes'], ['Record', 'Review daily observations and run status']],
        accessTitle: 'Your next experiment starts with a hypothesis.', accessBody: 'A quantitative research workbench for China A-shares.', footer: 'QuantTrace · Quantitative Research Workbench',
        meta: 'QuantTrace: a quantitative research workbench for China A-shares. Factor research, strategy backtesting and daily tracking.',
    },
    zh: {
        brand: '量研 · QuantTrace', descriptor: '量化实验工作台', home: '量研 QuantTrace 首页', navigation: '主导航', method: '研究方法', preview: '产品预览', login: '登录',
        headline: ['让每一个假设，', '都经得起验证。'], subtitle: '从因子研究到策略回测，再到每日跟踪。', explore: '探索量研', stepsLabel: '三个研究步骤', viewExample: '查看示例', demo: '演示内容',
        previewTitle: '短期反转的一次实验。', previewIntro: '用一个具体问题，走过完整研究流程。', previewNote: '以下为交互演示，不执行真实研究任务。', stagesLabel: '研究阶段', alpha: 'Alpha 表达式',
        stages: [
            { title: '提出假设', description: '明确研究思路，构建可检验的假设。', label: '研究假设', detail: '近期下跌较多的股票，之后是否存在短期反转？', action: '查看验证方式', body: '把直觉写成表达式，再检查它能否得到研究结果的支持。' },
            { title: '验证结果', description: '通过回测与检验，评估假设的有效性。', label: '验证方式', detail: '结合因子表现、策略收益与回撤，检查假设在历史区间内的表现。', action: '查看后续观察', body: '收益之外，也关注结果是否稳定，以及结论依赖哪些研究设定。' },
            { title: '持续观察', description: '每日跟踪表现，观察长期稳定性。', label: '后续观察', detail: '从研究结果开始每日跟踪，继续观察后续交易日的策略表现。', action: '重新查看假设', body: '历史回测提供起点，后续观察继续积累证据。' },
        ],
        validation: [['因子表现', '观察信号与后续收益的关系'], ['策略回测', '检查收益、回撤和持仓变化'], ['研究依据', '保留表达式、参数与数据上下文']],
        tracking: [['起点', '已有研究结果'], ['频率', '交易日收盘后'], ['记录', '逐日查看观察结果与运行状态']],
        accessTitle: '下一次研究，从一个假设开始。', accessBody: '面向 A 股研究者的量化实验工作台。', footer: '量研 · 量化实验工作台', meta: '量研 QuantTrace：从因子研究、策略回测到每日跟踪的量化实验工作台。',
    },
};
