'use strict';

var browserify = require('browserify');
var buffer = require('gulp-buffer');
var del = require('del');
var gulp = require('gulp');
var inject = require('gulp-inject');
var rev = require('gulp-rev');
var source = require('vinyl-source-stream');

var BUILD_DIR = 'volttroncentral/webroot/';
var APP_GLOB = '{css,js}/app-*';
var VENDOR_GLOB = '{css,js}/{normalize,vendor}-*';

gulp.task('default', ['watch']);
gulp.task('clean-app', cleanApp);
gulp.task('clean-vendor', cleanVendor);
gulp.task('css', ['clean-app'], css);
gulp.task('build', ['css', 'js', 'vendor'], htmlInject);
gulp.task('build-app', ['css', 'js'], htmlInject);
gulp.task('js', ['clean-app'], js);
gulp.task('watch', ['build'], watch);
gulp.task('vendor', ['clean-vendor'], vendor);

function cleanApp (callback) {
    del(BUILD_DIR + APP_GLOB, callback);
}

function cleanVendor(callback) {
    del(BUILD_DIR + VENDOR_GLOB, callback);
}

function css() {
    return gulp.src('ui-src/css/app.css')
        .pipe(rev())
        .pipe(gulp.dest(BUILD_DIR + 'css'));
}

function htmlInject() {
    return gulp.src('ui-src/index.html')
        .pipe(inject(gulp.src([VENDOR_GLOB, APP_GLOB], { cwd: BUILD_DIR}), { addRootSlash: false }))
        .pipe(gulp.dest(BUILD_DIR));
}

function js() {
    return browserify({
        bundleExternal: false,
        entries: './ui-src/js/app',
        extensions: ['.jsx'],
    })
        .transform('reactify')
        .bundle()
        .pipe(source('app.js'))
        .pipe(buffer())
        .pipe(rev())
        .pipe(gulp.dest(BUILD_DIR + 'js'));
}

function vendor() {
    gulp.src('node_modules/normalize.css/normalize.css')
        .pipe(rev())
        .pipe(gulp.dest(BUILD_DIR + 'css'));

    return browserify({
        noParse: [
            'bluebird/js/browser/bluebird.min',
            'd3/d3.min',
            'events',
            'jquery/dist/jquery.min',
            'node-uuid',
            'react/dist/react.min',
            'react-router/umd/ReactRouter.min',
        ],
    })
        .require([
            { file: 'bluebird/js/browser/bluebird.min', expose: 'bluebird' },
            { file: 'd3/d3.min', expose: 'd3' },
            'events',
            'flux',
            { file: 'jquery/dist/jquery.min', expose: 'jquery' },
            'node-uuid',
            { file: 'react/dist/react.min', expose: 'react' },
            'react/lib/keyMirror',
            { file: 'react-router/umd/ReactRouter.min', expose: 'react-router' },
        ])
        .bundle()
        .pipe(source('vendor.js'))
        .pipe(buffer())
        .pipe(rev())
        .pipe(gulp.dest(BUILD_DIR + 'js'));
}

function watch() {
    return gulp.watch(['ui-src/**/*'], ['build-app']);
}
