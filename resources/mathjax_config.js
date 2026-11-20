window.MathJax = {
    loader: {
        load: ['[tex]/color'],
        paths: {
            mathjax: '/static/vnoj/mathjax/3.2.0/es5'
        }
    },
    tex: {
        packages: {
            '[+]': ['color']
        },
        inlineMath: [
            ['~', '~'],
            ['$', '$'],
            ['\\(', '\\)']
        ],
        displayMath: [
            ['$$', '$$'],
            ['\\[', '\\]']
        ]
    },
    options: {
        enableMenu: false
    }
};
