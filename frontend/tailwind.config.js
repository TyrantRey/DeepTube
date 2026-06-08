/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                ac: {
                    bg: '#F8F8F0',     // 燕麥白底色
                    brown: '#4A3728',  // 經典邊框深棕
                    green: '#19C8B9',  // 機場青綠
                    orange: '#FF823A', // 暖陽橘
                    yellow: '#FBE870', // 西施惠黃
                    cream: '#FFFDF0',  // 對話框乳白
                }
            },
            boxShadow: {
                'ac-3d': '0 8px 0 #4A3728',
                'ac-3d-sm': '0 4px 0 #4A3728',
                'ac-3d-active': '0 0px 0 #4A3728',
            }
        },
    },
    plugins: [],
}